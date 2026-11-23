"""Preview and atomically apply scoped JSON edits on macOS and Linux.

The caller chooses a project and a relative file path. No personal settings are
discovered, no tools run, and no receipt is persisted here.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from uuid import uuid4

from pydantic import JsonValue, ValidationError

from stackwinnow.contracts import (
    ConfigApplyResult,
    ConfigFileState,
    ConfigPatch,
    ConfigValue,
    JsonConfigEdit,
    OperationResult,
    OperationStatus,
    OwnedConfigEdit,
)


class ConfigurationError(ValueError):
    """A configuration file could not be read or a patch could not be prepared."""


class ConfigurationConflict(ConfigurationError):
    """Input is unsupported, conflicts with an edit, or changed since preview."""


def _resolve_project_root(project_root: Path | str) -> str:
    try:
        return str(Path(project_root).resolve(strict=True))
    except (RuntimeError, OSError) as exc:
        # Path.resolve used RuntimeError for symlink loops before Python 3.13;
        # newer versions raise OSError(ELOOP). Other IO failures keep their meaning.
        if isinstance(exc, OSError) and exc.errno != errno.ELOOP:
            raise
        raise ConfigurationConflict(
            "The project path contains a symlink loop; correct it and preview again."
        ) from exc


def _json(value: object) -> str:
    # Python considers True == 1; JSON configuration must distinguish them.
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":"))


def _unique_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def _lossless_float(text: str) -> float:
    value = float(text)
    if not Decimal(text).is_finite() or Decimal(str(value)) != Decimal(text):
        raise ValueError("JSON number would lose precision when rewritten")
    return value


def _document(raw: bytes | None) -> dict[str, JsonValue]:
    if raw is None:
        return {}
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=_lossless_float,
        )
        if not isinstance(value, dict):
            raise ValueError("top-level JSON value must be an object")
        _json(value)  # Also rejects overflow such as 1e999 in nested values.
        return value
    except (ValueError, UnicodeError, InvalidOperation, RecursionError) as exc:
        # Do not include existing configuration values in diagnostics.
        raise ConfigurationConflict(
            "Configuration must be UTF-8 JSON with an object root, unique keys, "
            "and finite numbers that round-trip without precision loss. "
            "Comments and trailing commas are not supported."
        ) from exc


@contextmanager
def _parent(project_root: str, relative_path: str) -> Iterator[tuple[int, str]]:
    """Hold directory descriptors so path traversal never follows child symlinks."""
    if os.name != "posix":
        raise ConfigurationConflict("Configuration writes currently support macOS and Linux.")
    if _resolve_project_root(project_root) != project_root:
        raise ConfigurationConflict("The project path now resolves elsewhere; preview again.")
    descriptors: list[int] = []
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        descriptors.append(os.open(project_root, flags))
        parts = PurePosixPath(relative_path).parts
        for part in parts[:-1]:
            descriptors.append(os.open(part, flags, dir_fd=descriptors[-1]))
        yield descriptors[-1], parts[-1]
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise ConfigurationConflict(
                "Configuration parents must be real directories; symlink paths are unsupported."
            ) from exc
        raise
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _stamp(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_mode,
        info.st_nlink,
    )


def _read(
    parent: int, name: str, *, limit: int | None = None
) -> tuple[bytes | None, ConfigFileState]:
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    except FileNotFoundError:
        return None, ConfigFileState(exists=False)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ConfigurationConflict("Configuration files cannot be symlinks.") from exc
        raise
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ConfigurationConflict(
                "Configuration must be a regular file with a single hard link."
            )
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            raw = source.read() if limit is None else source.read(limit + 1)
        if limit is not None and len(raw) > limit:
            raise ConfigurationConflict("Configuration exceeds the supported size.")
        if _stamp(before) != _stamp(os.fstat(descriptor)):
            raise ConfigurationConflict("Configuration changed while it was being read.")
        return raw, ConfigFileState(
            exists=True, sha256=hashlib.sha256(raw).hexdigest(), mode=stat.S_IMODE(before.st_mode)
        )
    finally:
        os.close(descriptor)


def _prepare(
    root: str,
    relative_path: str,
    tool_id: str,
    requests: Sequence[JsonConfigEdit],
    raw: bytes | None,
    state: ConfigFileState,
) -> tuple[ConfigPatch, bytes | None]:
    document = _document(raw)
    changes: list[OwnedConfigEdit] = []
    created: list[tuple[str, ...]] = []
    paths = [request.key_path for request in requests]
    for index, key_path in enumerate(paths):
        for other in paths[index + 1 :]:
            shorter = min(len(key_path), len(other))
            if key_path[:shorter] == other[:shorter]:
                raise ConfigurationConflict("Requested key paths must not overlap or repeat.")
    for request in requests:
        target = document
        for depth, key in enumerate(request.key_path[:-1], start=1):
            if key not in target:
                target[key] = {}
                created.append(request.key_path[:depth])
            child = target[key]
            if not isinstance(child, dict):
                raise ConfigurationConflict("An edited key's parent is not a JSON object.")
            target = child
        key = request.key_path[-1]
        original = ConfigValue(exists=key in target, value=deepcopy(target.get(key)))
        if original.exists and _json(original.value) == _json(request.value):
            continue
        if original.exists and not request.replace_existing:
            raise ConfigurationConflict(
                "A different value already exists. Review it and explicitly request replacement."
            )
        target[key] = deepcopy(request.value)
        changes.append(
            OwnedConfigEdit(
                key_path=request.key_path, original=original, written=deepcopy(request.value)
            )
        )
    if changes:
        rendered = (json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(
            "utf-8"
        )
        written = ConfigFileState(
            exists=True,
            sha256=hashlib.sha256(rendered).hexdigest(),
            mode=state.mode if state.exists else 0o600,
        )
    else:
        rendered, written = raw, state
    return (
        ConfigPatch(
            project_root=root,
            relative_path=relative_path,
            tool_id=tool_id,
            expected_file=state,
            written_file=written,
            edits=tuple(changes),
            created_objects=tuple(created),
        ),
        rendered,
    )


def plan_json_edits(
    project_root: Path | str,
    relative_path: Path | str,
    *,
    tool_id: str,
    edits: Sequence[JsonConfigEdit],
) -> ConfigPatch:
    """Read and preview one file. Parents must exist; preview never creates files.

    Raise ConfigurationConflict for unsupported input or an existing-value
    conflict, ConfigurationError for IO failures, and ValidationError for
    invalid request contracts. The result can be serialized before mutation.
    """
    try:
        root = _resolve_project_root(project_root)
        relative = Path(relative_path).as_posix()
        # Validate scope before passing any caller-supplied path to open().
        scope = ConfigPatch(
            project_root=root,
            relative_path=relative,
            tool_id=tool_id,
            expected_file=ConfigFileState(exists=False),
            written_file=ConfigFileState(exists=False),
        )
        requests = tuple(JsonConfigEdit.model_validate(edit.model_dump()) for edit in edits)
        with _parent(scope.project_root, scope.relative_path) as (parent, name):
            raw, state = _read(parent, name)
            patch, _ = _prepare(root, relative, tool_id, requests, raw, state)
            return patch
    except OSError as exc:
        raise ConfigurationError(
            f"Cannot read the configuration path ({exc.strerror}). Its parent must exist."
        ) from exc


def _check_current(
    patch: ConfigPatch, parent: int, name: str, *, limit: int | None = None
) -> bytes | None:
    # Reopen the path as well as checking the held descriptor, detecting a
    # renamed/replaced parent before publication. No symlink is followed.
    with _parent(patch.project_root, patch.relative_path) as (current_parent, _):
        current = os.fstat(current_parent)
        held = os.fstat(parent)
        if (current.st_dev, current.st_ino) != (held.st_dev, held.st_ino):
            raise ConfigurationConflict("The configuration's parent directory changed.")
    raw, state = _read(
        parent,
        name,
        limit=limit if limit is not None else 4 * 1024 * 1024 if patch.format == "toml" else None,
    )
    if state != patch.expected_file:
        raise ConfigurationConflict(
            "Configuration content, existence, or permissions changed since preview; preview again."
        )
    return raw


def _apply_edits(patch: ConfigPatch, *, prepare=_prepare, format="json") -> ConfigApplyResult:
    """Apply the previewed changes, returning actual ownership separately from intent.

    Failures before publication return no ownership. Unchanged existing values
    are skipped without being adopted. A published write retains ownership if
    subsequent temporary-file cleanup fails. The executor must persist intent
    before this call and serialize its own concurrent project operations.
    """
    checked: ConfigPatch | None = None
    published = False
    try:
        # Frozen models can still contain mutable JSON children or be copied
        # without validation. Revalidate and detach the complete input.
        checked = ConfigPatch.model_validate(patch.model_dump(warnings=False))
        if checked.format != format:
            raise ConfigurationConflict("Configuration format does not match the selected writer.")
        with _parent(checked.project_root, checked.relative_path) as (parent, name):
            raw = _check_current(checked, parent, name)
            requests = tuple(
                JsonConfigEdit(key_path=edit.key_path, value=edit.written, replace_existing=True)
                for edit in checked.edits
            )
            rebuilt, rendered = prepare(
                checked.project_root,
                checked.relative_path,
                checked.tool_id,
                requests,
                raw,
                checked.expected_file,
            )
            if _json(rebuilt.model_dump(mode="json")) != _json(checked.model_dump(mode="json")):
                raise ConfigurationConflict(
                    "Preview values, ownership, or output digest are inconsistent; preview again."
                )
            if not checked.edits:
                return ConfigApplyResult(
                    result=OperationResult(
                        status=OperationStatus.SKIPPED,
                        tool_id=checked.tool_id,
                        message="Configuration already matches; no values were written or adopted.",
                    )
                )
            temporary = f".stackwinnow-{uuid4().hex}.tmp"
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent
            )
            try:
                with os.fdopen(descriptor, "wb") as output:
                    output.write(rendered)
                    output.flush()
                    os.fchmod(output.fileno(), checked.written_file.mode)
                    os.fsync(output.fileno())
                _check_current(checked, parent, name)
                if checked.expected_file.exists:
                    os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
                else:
                    # A hard-link publication is atomic and fails if another
                    # writer creates the destination after the final check.
                    os.link(
                        temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False
                    )
                published = True
            finally:
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass
        return ConfigApplyResult(
            result=OperationResult(
                status=OperationStatus.SUCCEEDED,
                tool_id=checked.tool_id,
                message="Applied the previewed configuration edits.",
            ),
            ownership=checked,
        )
    except (ConfigurationConflict, ValidationError) as exc:
        message = (
            str(exc) if isinstance(exc, ConfigurationConflict) else "Invalid preview contract."
        )
        status = OperationStatus.BLOCKED
    except OSError as exc:
        status = OperationStatus.FAILED
        if published:
            message = (
                "Configuration was applied, but temporary-file cleanup failed. Retain ownership."
            )
        elif isinstance(exc, FileExistsError):
            status = OperationStatus.BLOCKED
            message = "The configuration file appeared after preview; preview again."
        elif isinstance(exc, FileNotFoundError):
            status = OperationStatus.BLOCKED
            message = "The configuration path disappeared after preview; preview again."
        else:
            message = f"Configuration IO failed ({exc.strerror}); no configuration was published."
    return ConfigApplyResult(
        result=OperationResult(
            status=status,
            tool_id=checked.tool_id if checked else None,
            message=message,
            errors=[message],
        ),
        ownership=checked if published else None,
    )


def apply_json_edits(patch: ConfigPatch) -> ConfigApplyResult:
    """Apply a JSON preview with atomic publication and retained ownership."""
    return _apply_edits(patch)

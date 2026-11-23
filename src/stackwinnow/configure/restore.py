"""Preview and restore receipt-owned settings without adopting foreign values.

The low-level apply function deliberately does not acquire the project lock or
write receipts. A lifecycle executor must hold the shared lock, validate the
ownership against its durable record, and persist the complete restore intent
before calling it. This matches the existing configuration apply primitives.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import ValidationError

from stackwinnow.configure import patches
from stackwinnow.configure.conflicts import _classify_owned, _document, _supported
from stackwinnow.contracts import (
    ConfigFileState,
    ConfigPatch,
    ConflictKind,
    Contract,
    FileState,
    JsonKeyPath,
    KeyConflict,
    OperationResult,
    OperationStatus,
)


class ConfigRestorePlan(Contract):
    """A reviewable restore intent carrying the original ownership evidence."""

    schema_version: Literal[1] = 1
    ownership: ConfigPatch
    expected_file: ConfigFileState | None
    file_state: FileState
    restore_keys: tuple[JsonKeyPath, ...] = ()
    retained_keys: tuple[KeyConflict, ...] = ()
    blocked: bool = False
    message: str


class ConfigRestoreResult(Contract):
    schema_version: Literal[1] = 1
    result: OperationResult
    plan: ConfigRestorePlan
    published: bool = False
    released_keys: tuple[JsonKeyPath, ...] = ()
    restored_file: ConfigFileState | None = None


class RuntimeReferenceReport(Contract):
    """Conservative live references, including foreign configuration entries."""

    schema_version: Literal[1] = 1
    file_state: FileState
    retained_paths: tuple[str, ...]


def _read(patch: ConfigPatch):
    with patches._parent(patch.project_root, patch.relative_path) as (parent, name):
        return patches._read(parent, name, limit=4 * 1024 * 1024)


def _restore_document(document: dict, patch: ConfigPatch, keys: set[tuple[str, ...]]) -> dict:
    document = deepcopy(document)
    for edit in patch.edits:
        if edit.key_path not in keys:
            continue
        parent = document
        for component in edit.key_path[:-1]:
            parent = parent[component]
        if edit.original.exists:
            parent[edit.key_path[-1]] = deepcopy(edit.original.value)
        else:
            del parent[edit.key_path[-1]]
    for path in sorted(patch.created_objects, key=len, reverse=True):
        if not any(key[: len(path)] == path for key in keys):
            continue
        parent = document
        for component in path[:-1]:
            if not isinstance(parent, dict):
                break
            parent = parent.get(component)
        if isinstance(parent, dict) and parent.get(path[-1]) == {}:
            del parent[path[-1]]
    return document


def _render(raw: bytes, patch: ConfigPatch, keys: set[tuple[str, ...]]) -> bytes:
    original = _document(patch, raw)
    restored = _restore_document(original, patch, keys)
    if patch.format == "json":
        return (json.dumps(restored, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()

    # Codex writers append a single canonical table. Remove only those exact
    # bytes, then validate the entire document's semantics. User-reformatted
    # tables or inserted comments are preserved rather than reconstructed.
    from stackwinnow.configure.codex import GRAPHIFY_KEY, KEY, _value

    rendered = raw
    for edit in patch.edits:
        if edit.key_path not in keys:
            continue
        if (
            edit.key_path not in (KEY, GRAPHIFY_KEY)
            or edit.original.exists
            or not isinstance(edit.written, dict)
        ):
            raise patches.ConfigurationConflict("This TOML ownership shape cannot be restored.")
        stanza = "\n[mcp_servers." + edit.key_path[-1] + "]\n"
        stanza += "".join(
            json.dumps(k) + " = " + _value(v) + "\n" for k, v in sorted(edit.written.items())
        )
        block = stanza.encode("utf-8")
        if rendered.count(block) != 1:
            raise patches.ConfigurationConflict(
                "The owned TOML table was reformatted; preserve it and inspect manually."
            )
        rendered = rendered.replace(block, b"", 1)
    parsed = _document(patch, rendered)
    # TOML child headers implicitly create mcp_servers. Removing the final
    # child makes that implicit empty object disappear, even when a different
    # adapter originally created it. An explicit user header remains in bytes.
    if restored.get("mcp_servers") == {} and "mcp_servers" not in parsed:
        del restored["mcp_servers"]
    if parsed != restored:
        raise patches.ConfigurationConflict(
            "Removing the TOML table would change unrelated settings; preserve it."
        )
    return rendered


def plan_config_restore(ownership: ConfigPatch) -> ConfigRestorePlan:
    """Preview reverting only unchanged owned keys; never recreate user removals."""
    patch = ConfigPatch.model_validate(ownership.model_dump(warnings=False))
    if not _supported(patch):
        return ConfigRestorePlan(
            ownership=patch,
            expected_file=None,
            file_state=FileState.UNSUPPORTED,
            blocked=True,
            message="Configuration format/path is unsupported; preserve it.",
        )
    try:
        try:
            raw, state = _read(patch)
        except FileNotFoundError:
            raw, state = None, ConfigFileState(exists=False)
        if raw is None:
            return ConfigRestorePlan(
                ownership=patch,
                expected_file=state,
                file_state=FileState.MISSING,
                message="Configuration is absent; no values will be recreated.",
            )
        document = _document(patch, raw)
        keys = _classify_owned(document, patch)
        clean = tuple(key.key_path for key in keys if key.kind == ConflictKind.CLEAN)
        retained = tuple(key for key in keys if key.kind != ConflictKind.CLEAN)
        blocked = False
        message = "Restore unchanged owned values and preserve user changes."
        if clean:
            try:
                _render(raw, patch, set(clean))
            except patches.ConfigurationConflict as exc:
                blocked, message = True, str(exc)
        return ConfigRestorePlan(
            ownership=patch,
            expected_file=state,
            file_state=FileState.READABLE if state == patch.written_file else FileState.STALE,
            restore_keys=clean,
            retained_keys=retained,
            blocked=blocked,
            message=message,
        )
    except (OSError, RecursionError, patches.ConfigurationConflict):
        return ConfigRestorePlan(
            ownership=patch,
            expected_file=None,
            file_state=FileState.UNREADABLE,
            blocked=True,
            message="Configuration is unreadable or unsafe; preserve it.",
        )


def apply_config_restore(plan: ConfigRestorePlan) -> ConfigRestoreResult:
    """Apply under the caller's project lock and durable journal; keep empty files.

    The original ownership always remains in the result, including failures after
    publication. The caller may release only released_keys after persisting this
    outcome. No-op matching settings never establish new ownership.
    """
    plan = ConfigRestorePlan.model_validate(plan.model_dump(warnings=False))
    patch = plan.ownership
    published = False
    restored_file = None
    released: tuple[tuple[str, ...], ...] = ()
    try:
        current = plan_config_restore(patch)
        if current != plan:
            raise patches.ConfigurationConflict(
                "Configuration changed since preview; preview again."
            )
        if plan.blocked:
            raise patches.ConfigurationConflict(plan.message)
        if not plan.restore_keys:
            return ConfigRestoreResult(
                plan=plan,
                result=OperationResult(
                    status=OperationStatus.SKIPPED,
                    tool_id=patch.tool_id,
                    message="No unchanged owned settings need restoration.",
                ),
                released_keys=tuple(
                    k.key_path for k in plan.retained_keys if k.kind == ConflictKind.USER_REMOVED
                )
                if plan.file_state != FileState.MISSING
                else tuple(e.key_path for e in patch.edits),
                restored_file=plan.expected_file,
            )
        expected = patch.model_copy(update={"expected_file": plan.expected_file})
        with patches._parent(patch.project_root, patch.relative_path) as (parent, name):
            raw = patches._check_current(expected, parent, name, limit=4 * 1024 * 1024)
            rendered = _render(raw, patch, set(plan.restore_keys))
            temporary = f".stackwinnow-restore-{uuid4().hex}.tmp"
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent
            )
            try:
                try:
                    with os.fdopen(descriptor, "wb", closefd=False) as output:
                        output.write(rendered)
                        output.flush()
                        os.fchmod(descriptor, plan.expected_file.mode)
                        os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                patches._check_current(expected, parent, name, limit=4 * 1024 * 1024)
                os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
                published = True
                restored_file = ConfigFileState(
                    exists=True,
                    sha256=hashlib.sha256(rendered).hexdigest(),
                    mode=plan.expected_file.mode,
                )
                released = plan.restore_keys + tuple(
                    key.key_path
                    for key in plan.retained_keys
                    if key.kind == ConflictKind.USER_REMOVED
                )
            finally:
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass
        status, message = OperationStatus.SUCCEEDED, "Restored unchanged manager-owned settings."
    except (patches.ConfigurationConflict, ValidationError) as exc:
        status = OperationStatus.BLOCKED
        message = (
            str(exc) if isinstance(exc, patches.ConfigurationConflict) else "Invalid restore plan."
        )
    except (OSError, RecursionError):
        status = OperationStatus.FAILED
        message = (
            "Restoration was published but cleanup failed; persist the outcome and retain the journal."
            if published
            else "Configuration restoration failed before publication; retain ownership."
        )
    return ConfigRestoreResult(
        plan=plan,
        published=published,
        released_keys=released,
        restored_file=restored_file,
        result=OperationResult(status=status, tool_id=patch.tool_id, message=message),
    )


def referenced_runtime_paths(
    ownership: ConfigPatch,
    runtime_paths: Sequence[str],
    *,
    restorations: Sequence[ConfigRestorePlan] = (),
) -> RuntimeReferenceReport:
    """Read live JSON/Codex TOML, including foreign keys, for managed references.

    Run after configuration cleanup and under the lifecycle lock before deletion.
    Unreadable/unsupported documents retain every supplied path. Textual matches
    are deliberately conservative, including paths embedded in shell arguments.
    This is reference evidence only; it never establishes ownership/deletability.
    restorations projects reviewed cleanup in memory for preview only. Deletion
    must call again without restorations against the live, durably recorded result.
    """
    patch = ConfigPatch.model_validate(ownership.model_dump(warnings=False))
    candidates: dict[str, tuple[str, str]] = {}
    root = Path(patch.project_root)
    for raw in runtime_paths:
        path = Path(raw) if Path(raw).is_absolute() else root / raw
        if "\x00" in raw or ".." in path.parts or not path.is_relative_to(root / ".stackwinnow"):
            raise patches.ConfigurationConflict(
                "Runtime references must use managed project paths."
            )
        candidates[raw] = (str(path), path.relative_to(root).as_posix())
    if not _supported(patch):
        return RuntimeReferenceReport(
            file_state=FileState.UNSUPPORTED, retained_paths=tuple(candidates)
        )
    try:
        try:
            raw, state = _read(patch)
        except FileNotFoundError:
            raw = None
        if raw is None:
            return RuntimeReferenceReport(file_state=FileState.MISSING, retained_paths=())
        for restoration in restorations:
            if (
                restoration.ownership.project_root == patch.project_root
                and restoration.ownership.relative_path == patch.relative_path
                and not restoration.blocked
                and restoration.restore_keys
            ):
                raw = _render(raw, restoration.ownership, set(restoration.restore_keys))
        document = _document(patch, raw)

        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for child in value.values():
                    yield from strings(child)
            elif isinstance(value, list):
                for child in value:
                    yield from strings(child)

        values = list(strings(document))
        # Also recognize direct aliases such as /project/bin/server symlinking
        # into a managed runtime. No executable or shell expression is run.
        for value in tuple(values):
            if value.startswith(("/", "./", ".stackwinnow/")):
                path = Path(value)
                try:
                    values.append(str((path if path.is_absolute() else root / path).resolve()))
                except (OSError, RuntimeError, ValueError):
                    return RuntimeReferenceReport(
                        file_state=FileState.UNREADABLE, retained_paths=tuple(candidates)
                    )
        retained = tuple(
            raw
            for raw, forms in candidates.items()
            if any(form in value for form in forms for value in values)
        )
        return RuntimeReferenceReport(file_state=FileState.READABLE, retained_paths=retained)
    except (OSError, RecursionError, patches.ConfigurationConflict):
        return RuntimeReferenceReport(
            file_state=FileState.UNREADABLE, retained_paths=tuple(candidates)
        )

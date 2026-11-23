"""Reviewed configuration cleanup and conservative, journaled runtime removal."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field

from stackwinnow import _removal_fs
from stackwinnow.adapters._managed import directories, read_json, record_for
from stackwinnow.configure import (
    ConfigRestorePlan,
    apply_config_restore,
    plan_config_restore,
    referenced_runtime_paths,
)
from stackwinnow.configure.patches import _parent
from stackwinnow.contracts import (
    ConfigFileState,
    ConfigPatch,
    ConflictKind,
    Contract,
    Identifier,
    OperationStatus,
    Sha256,
)
from stackwinnow.installer import (
    ConfigurationRelease,
    ExecutionRecord,
    InstallerError,
    RuntimeRelease,
    ToolRetirement,
    _now,
    _persist,
)
from stackwinnow.runtime.remove import _is_managed, _is_project_data, _normalise, plan_removal
from stackwinnow.state.lock import project_lock

# Deliberately narrower than general receipt ownership: no caller-chosen commands
# or directories, and no recursive deletion of retained project-state parents.
RUNTIMES = {
    "graphify": (".stackwinnow/envs/graphify",),
    "headroom": (".stackwinnow/envs/headroom/python",),
    "promptfoo": (".stackwinnow/envs/promptfoo/node",),
    "playwright-mcp": (
        ".stackwinnow/envs/playwright-mcp/node",
        ".stackwinnow/envs/playwright-mcp/browsers",
    ),
}
DATA = {
    "graphify": ".stackwinnow/graphify",
    "headroom": ".stackwinnow/headroom",
    "promptfoo": ".stackwinnow/promptfoo",
    "playwright-mcp": ".stackwinnow/envs/playwright-mcp",
}
JOURNALS = ".stackwinnow/removals"


class RuntimeRemoval(Contract):
    tool_id: Identifier
    path: str
    action: Literal["remove", "retain", "absent", "released"]
    reason: str
    snapshot_sha256: Sha256 | None = None


class RemovalPlan(Contract):
    schema_version: Literal[1] = 1
    project_root: str
    tool_ids: list[Identifier]
    receipts_sha256: Sha256
    configuration: list[ConfigRestorePlan]
    runtimes: list[RuntimeRemoval]
    retained_paths: list[str]
    directory_identities: dict[str, tuple[int, int]]


class RemovalResult(Contract):
    schema_version: Literal[1] = 1
    status: OperationStatus
    project_root: str
    dry_run: bool = False
    message: str
    removed_paths: list[str] = Field(default_factory=list)
    retained_paths: list[str] = Field(default_factory=list)
    retired_tools: list[str] = Field(default_factory=list)
    journal: str | None = None


def _root(value: str | Path) -> Path:
    root = Path(value).expanduser().absolute()
    if not root.is_dir() or root.resolve(strict=True) != root:
        raise InstallerError("Select an existing project without path aliases.")
    return root


def _record_digest(record: ExecutionRecord) -> str:
    return hashlib.sha256(record.model_dump_json().encode()).hexdigest()


def _patches(record: ExecutionRecord) -> list[ConfigPatch]:
    found = {}
    history = [s for retirement in record.retirements for s in retirement.original_steps]
    for step in record.steps + history:
        if step.dry_run:
            continue
        for patch in step.configuration_ownership + step.configuration_intents:
            if patch.project_root != record.project_root or patch.tool_id != step.tool_id:
                raise InstallerError("Configuration ownership disagrees with its receipt.")
            found[patch.model_dump_json()] = patch
    return list(found.values())


def _restores(record: ExecutionRecord, selected: list[str]) -> list[ConfigRestorePlan]:
    found = {}
    claims = {}
    for step in record.steps:
        if step.dry_run or step.tool_id not in selected:
            continue
        for patch in step.configuration_ownership:
            if not patch.edits:
                continue
            key = patch.model_dump_json()
            if key in found:
                continue
            for edit in patch.edits:
                claim = (patch.relative_path, edit.key_path)
                if any(
                    path == patch.relative_path
                    and value != key
                    and (
                        prior[: len(edit.key_path)] == edit.key_path
                        or edit.key_path[: len(prior)] == prior
                    )
                    for (path, prior), value in claims.items()
                ):
                    raise InstallerError("Overlapping configuration ownership needs inspection.")
                claims[claim] = key
            found[key] = plan_config_restore(patch)
    return list(found.values())


def _reference_patches(record):
    patches = _patches(record)
    patches.extend(release.ownership for release in record.configuration_releases)
    for path, format in (
        (".codex/config.toml", "toml"),
        ("promptfooconfig.stackwinnow.json", "json"),
        ("promptfooconfig.stackwinnow.openai.json", "json"),
    ):
        # Read-only descriptors for known foreign settings, never ownership.
        patches.append(
            ConfigPatch(
                project_root=record.project_root,
                relative_path=path,
                tool_id="graphify",
                format=format,
                expected_file=ConfigFileState(exists=False),
                written_file=ConfigFileState(exists=False),
            )
        )
    return list({(p.format, p.relative_path): p for p in patches}.values())


def _unfinished(root: Path) -> None:
    directories(root, JOURNALS)
    directory = root / JOURNALS
    if not directory.exists():
        return
    paths = []
    for path in directory.iterdir():
        paths.append(path)
        if len(paths) > 1000:
            raise InstallerError(
                "Removal journal limit reached; inspect and archive completed journals."
            )
    for path in paths:
        if path.suffix != ".json":
            raise InstallerError("Unfamiliar removal journal data requires inspection.")
        value = read_json(path)
        if value.get("project_root") != str(root) or value.get("status") not in {
            "succeeded",
            "failed",
            "blocked",
        }:
            raise InstallerError("An interrupted removal needs journal inspection before retrying.")


def _overlap(a: str, b: str) -> bool:
    return Path(a).is_relative_to(b) or Path(b).is_relative_to(a)


def _owners_digest(record, tool, relative):
    root = Path(record.project_root)
    owners = [
        s.model_dump(mode="json", exclude={"configuration_ownership", "configuration_intents"})
        for s in record.steps
        if s.tool_id == tool
        and not s.dry_run
        and any((root / relative).is_relative_to(_normalise(p, root)) for p in s.owned_paths)
    ]
    return hashlib.sha256(json.dumps(owners, sort_keys=True).encode()).hexdigest()


def plan_removal_lifecycle(project_root: str | Path, tool_ids: list[str]) -> RemovalPlan:
    """Read-only review, including references after the proposed clean restorations."""
    root = _root(project_root)
    if not tool_ids or len(tool_ids) != len(set(tool_ids)) or set(tool_ids) - RUNTIMES.keys():
        raise InstallerError("Select unique supported tool IDs: " + ", ".join(RUNTIMES))
    _unfinished(root)
    record = record_for(root)
    patches = _reference_patches(record)
    restores = _restores(record, tool_ids)
    # Exercise the shared ownership classifier, including aliases/failed claims.
    classification = plan_removal(str(root), tool_ids, _record=record)
    retained_names = set()

    def protect(raw):
        absolute = Path(raw) if Path(raw).is_absolute() else root / raw
        retained_names.update((str(absolute), _normalise(raw, root)))

    for item in classification.retained:
        protect(item.path)
    for step in record.steps:
        if not step.dry_run:
            for evidence in step.evidence:
                absolute = (
                    Path(evidence.source)
                    if Path(evidence.source).is_absolute()
                    else root / evidence.source
                )
                if _is_project_data(str(absolute), root):
                    protect(evidence.source)
    candidates = [path for tool in tool_ids for path in RUNTIMES[tool]]
    references = set()
    for patch in patches:
        references.update(
            referenced_runtime_paths(patch, candidates, restorations=restores).retained_paths
        )
    protected_tools = {
        p.ownership.tool_id
        for p in restores
        if p.blocked or any(k.kind != ConflictKind.USER_REMOVED for k in p.retained_keys)
    }
    claims = []
    unsafe_claims = []
    for step in record.steps:
        if step.dry_run:
            continue
        for raw in step.owned_paths:
            if ".." in Path(raw).parts:
                raise InstallerError("Recorded ownership contains traversal; inspect it.")
            claims.append((step, _normalise(raw, root)))
            absolute = Path(raw) if Path(raw).is_absolute() else root / raw
            if not _is_managed(absolute, root):
                unsafe_claims.append(_normalise(raw, root))
    runtimes = []
    for tool in tool_ids:
        for relative in RUNTIMES[tool]:
            path = root / relative
            action, reason, digest = "retain", "No exclusive successful runtime ownership.", None
            allowed_owners = {str(path)}
            if tool == "playwright-mcp":
                allowed_owners.add(str(root / DATA[tool]))
            owners = [s for s, p in claims if p in allowed_owners and s.tool_id == tool]
            conflicting = any(
                _overlap(str(path), p)
                and (s.tool_id != tool or s.status != OperationStatus.SUCCEEDED)
                for s, p in claims
            )
            conflicting = conflicting or any(_overlap(str(path), p) for p in unsafe_claims)
            conflicting = conflicting or any(
                retired.tool_id != tool
                and (
                    _overlap(str(path), _normalise(raw, root))
                    or _overlap(
                        str(path), str(Path(raw) if Path(raw).is_absolute() else root / raw)
                    )
                )
                for retired in record.retirements
                for raw in retired.retained_paths
            )
            retained_child = any(Path(name).is_relative_to(path) for name in retained_names)
            if not os.path.lexists(path):
                action, reason = "absent", "Runtime is absent; no deletion is authorized."
                if any(
                    r.tool_id == tool
                    and r.path == relative
                    and r.owners_sha256 == _owners_digest(record, tool, relative)
                    for r in record.runtime_releases
                ):
                    action, reason = (
                        "released",
                        "A journaled earlier removal released these exact owners.",
                    )
            elif not _is_managed(path, root):
                reason = "Runtime path is linked or outside the managed directory."
            elif conflicting:
                reason = "Another tool or failed step retains this runtime."
            elif retained_child:
                reason = "The runtime contains a resource designated for retention."
            elif tool in protected_tools:
                reason = "Preserved or blocked owned settings retain this tool's runtime."
            elif relative in references:
                reason = "Configuration still references this runtime after cleanup."
            elif owners and all(s.status == OperationStatus.SUCCEEDED for s in owners):
                digest = _removal_fs.snapshot(str(root), relative)
                if digest is not None:
                    action, reason = (
                        "remove",
                        "Exclusive supported runtime; no preserved reference.",
                    )
            runtimes.append(
                RuntimeRemoval(
                    tool_id=tool,
                    path=relative,
                    action=action,
                    reason=reason,
                    snapshot_sha256=digest,
                )
            )
    retained = {i.path for i in classification.retained}
    retained.update(DATA[t] for t in tool_ids if os.path.lexists(root / DATA[t]))
    retained.update(r.path for r in runtimes if r.action == "retain")
    identities = {}
    paths = {root, *(root / DATA[t] for t in tool_ids)}
    for runtime in runtimes:
        paths.update((root / runtime.path).parents)
    for path in paths:
        if path.is_relative_to(root) and path.is_dir() and not path.is_symlink():
            info = path.stat()
            identities[path.relative_to(root).as_posix()] = (info.st_dev, info.st_ino)
    return RemovalPlan(
        project_root=str(root),
        tool_ids=tool_ids,
        receipts_sha256=_record_digest(record),
        configuration=restores,
        runtimes=runtimes,
        retained_paths=sorted(retained),
        directory_identities=identities,
    )


def load_removal_plan(path: str | Path) -> RemovalPlan:
    return RemovalPlan.model_validate(read_json(Path(path)))


def _journal(root: Path, relative: str, value: dict) -> None:
    directories(root, JOURNALS, create=True)
    with _parent(str(root), relative) as (parent, name):
        temporary = ".removal-" + uuid4().hex
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent)
        try:
            raw = json.dumps(value, indent=2).encode()
            if len(raw) > 4 * 1024 * 1024:
                raise InstallerError("Removal journal exceeds its size limit.")
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(descriptor)
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            os.close(descriptor)
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass


def _release(record, patch, keys):
    for step in record.steps:
        step.configuration_ownership = [
            p.model_copy(update={"edits": tuple(e for e in p.edits if e.key_path not in keys)})
            if p == patch
            else p
            for p in step.configuration_ownership
        ]
        step.configuration_ownership = [p for p in step.configuration_ownership if p.edits]


def _restored_files(record, tool):
    restored = {}
    for release in record.configuration_releases:
        patch = release.ownership
        if patch.tool_id != tool or release.restored_file is None:
            continue
        current = plan_config_restore(patch).expected_file
        if current == release.restored_file:
            restored[patch.relative_path] = current
    return restored


def apply_removal(plan: RemovalPlan, *, dry_run: bool = False) -> RemovalResult:
    """Revalidate under the project lock, journal, restore, recheck, then delete."""
    checked = RemovalPlan.model_validate(plan.model_dump())
    root = _root(checked.project_root)

    def validate():
        if plan_removal_lifecycle(root, checked.tool_ids) != checked:
            raise InstallerError("Removal plan or current state changed; preview again.")

    if dry_run:
        validate()
        return RemovalResult(
            status=OperationStatus.SKIPPED,
            project_root=str(root),
            dry_run=True,
            message="Reviewed removal preview; no files changed.",
            retained_paths=checked.retained_paths,
        )
    if not checked.configuration and not any(
        r.action in {"remove", "released"} for r in checked.runtimes
    ):
        validate()
        return RemovalResult(
            status=OperationStatus.SKIPPED,
            project_root=str(root),
            message="No safe cleanup is available; retained resources are unchanged.",
            retained_paths=checked.retained_paths,
        )
    with project_lock(root):
        validate()
        record = record_for(root)
        original = record.model_copy(deep=True)
        operation = "remove-" + uuid4().hex
        relative = JOURNALS + "/" + operation + ".json"
        journal = {
            "schema_version": 1,
            "project_root": str(root),
            "status": "running",
            "plan": checked.model_dump(mode="json"),
            "original_record": original.model_dump(mode="json"),
            "configuration_results": [],
            "removed_paths": [],
            "phase": "configuration",
        }
        _journal(root, relative, journal)
        result = RemovalResult(
            status=OperationStatus.SUCCEEDED,
            project_root=str(root),
            message="Removal completed; retained data and settings are preserved.",
            retained_paths=checked.retained_paths,
            journal=relative,
        )
        try:
            # The only allowed changes between these previews are this operation's
            # previously journaled writes to the same configuration file.
            expected_files = {
                p.ownership.relative_path: p.expected_file for p in checked.configuration
            }
            for preview in checked.configuration:
                patch = preview.ownership
                current = plan_config_restore(patch)
                if current.expected_file != expected_files[patch.relative_path]:
                    raise InstallerError("Configuration changed during removal.")
                if (current.restore_keys, current.retained_keys, current.blocked) != (
                    preview.restore_keys,
                    preview.retained_keys,
                    preview.blocked,
                ):
                    raise InstallerError("Owned settings changed during removal.")
                journal["current_restore"] = current.model_dump(mode="json")
                _journal(root, relative, journal)
                outcome = apply_config_restore(current)
                journal["configuration_results"].append(outcome.model_dump(mode="json"))
                _journal(root, relative, journal)
                _release(record, patch, set(outcome.released_keys))
                if outcome.released_keys:
                    record.configuration_releases.append(
                        ConfigurationRelease(
                            operation_id=operation,
                            ownership=patch,
                            released_keys=list(outcome.released_keys),
                            restored_file=outcome.restored_file,
                        )
                    )
                _persist(record, project_root=str(root))
                if outcome.restored_file is not None:
                    expected_files[patch.relative_path] = outcome.restored_file
                if outcome.result.status in {OperationStatus.FAILED, OperationStatus.BLOCKED}:
                    # A blocked retained table must not prevent independent safe
                    # runtime cleanup, but a write/IO failure stops this operation.
                    if outcome.result.status == OperationStatus.FAILED:
                        raise InstallerError(outcome.result.message)
                    result.status = OperationStatus.BLOCKED
                    result.message = "Safe cleanup completed; blocked configuration and its runtime were retained."
            journal["phase"] = "runtimes"
            _journal(root, relative, journal)
            for runtime in checked.runtimes:
                if runtime.action != "remove":
                    continue
                if any(
                    runtime.path in referenced_runtime_paths(p, [runtime.path]).retained_paths
                    for p in _reference_patches(original)
                ):
                    raise InstallerError("A preserved configuration now references the runtime.")
                journal["current_runtime"] = runtime.path
                _journal(root, relative, journal)
                _removal_fs.remove_tree(str(root), runtime.path, runtime.snapshot_sha256)
                result.removed_paths.append(runtime.path)
                journal["removed_paths"] = result.removed_paths
                _journal(root, relative, journal)
                record.runtime_releases.append(
                    RuntimeRelease(
                        operation_id=operation,
                        tool_id=runtime.tool_id,
                        path=runtime.path,
                        owners_sha256=_owners_digest(record, runtime.tool_id, runtime.path),
                    )
                )
                _persist(record, project_root=str(root))
            for tool in checked.tool_ids:
                expected = [r for r in checked.runtimes if r.tool_id == tool]
                # Never reinterpret accidentally missing state as successful removal.
                if not expected or not all(
                    r.path in result.removed_paths or r.action == "released" for r in expected
                ):
                    continue
                if any(s.configuration_ownership for s in record.steps if s.tool_id == tool):
                    continue
                old_steps = [s for s in original.steps if s.tool_id == tool]
                data = root / DATA[tool]
                if data.exists() and (
                    data.stat().st_dev,
                    data.stat().st_ino,
                ) != checked.directory_identities.get(DATA[tool]):
                    raise InstallerError("Retained data directory moved during removal.")
                record.retirements.append(
                    ToolRetirement(
                        operation_id=operation,
                        tool_id=tool,
                        timestamp=_now(),
                        original_steps=old_steps,
                        retained_paths=sorted(
                            {
                                (
                                    Path(p).relative_to(root).as_posix()
                                    if Path(p).is_absolute() and Path(p).is_relative_to(root)
                                    else p
                                )
                                for s in old_steps
                                for p in s.owned_paths
                                if os.path.lexists(Path(p) if Path(p).is_absolute() else root / p)
                            }
                        ),
                        retained_identities={
                            DATA[tool]: (
                                (root / DATA[tool]).stat().st_dev,
                                (root / DATA[tool]).stat().st_ino,
                            )
                        }
                        if os.path.lexists(root / DATA[tool])
                        else {},
                        restored_files=_restored_files(record, tool),
                    )
                )
                record.steps = [s for s in record.steps if s.tool_id != tool]
                result.retired_tools.append(tool)
            _persist(record, project_root=str(root))
        except (OSError, ValueError, InstallerError) as exc:
            result.status = OperationStatus.FAILED
            result.message = "Removal stopped; inspect its journal and preview remaining resources."
            journal["error_type"] = type(exc).__name__
        journal["status"] = result.status.value
        journal["result"] = result.model_dump(mode="json")
        _journal(root, relative, journal)
        return result

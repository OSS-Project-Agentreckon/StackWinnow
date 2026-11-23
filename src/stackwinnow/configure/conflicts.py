"""Read-only reconciliation of a recorded ConfigPatch against the current file.

This module never writes, never follows a symlink, and never adopts a value.
It reuses the hardened read/parse primitives in :mod:`stackwinnow.configure.patches`
and reports collisions as structured, value-free verdicts.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import JsonValue

from stackwinnow.configure import patches
from stackwinnow.contracts import (
    ConfigPatch,
    ConfigReconcileReport,
    ConflictKind,
    FileState,
    JsonConfigEdit,
    KeyConflict,
)

_MISSING = object()


def _supported(patch: ConfigPatch) -> bool:
    return patch.format == "json" or patch.relative_path == ".codex/config.toml"


def _document(patch: ConfigPatch, raw: bytes | None) -> dict:
    if patch.format == "toml":
        from stackwinnow.configure.codex import document

        return document(raw)
    return patches._document(raw)


def _same_value(current: object, written: object) -> bool:
    try:
        return patches._json(current) == patches._json(written)
    except (TypeError, ValueError):
        # TOML dates/times and non-finite numbers are valid user values, but
        # cannot equal a value stored in the JSON-only ownership contract.
        return False


def _leaf(document: dict[str, JsonValue], key_path: Sequence[str]) -> object:
    """Return the value at ``key_path`` or ``_MISSING`` if any step is absent.

    A non-object encountered mid-path also yields ``_MISSING``: the owned leaf
    cannot exist beneath it.
    """
    current: object = document
    for key in key_path:
        if not isinstance(current, dict) or key not in current:
            return _MISSING
        current = current[key]
    return current


def _classify_owned(document: dict[str, JsonValue], patch: ConfigPatch) -> list[KeyConflict]:
    conflicts: list[KeyConflict] = []
    for edit in patch.edits:
        current = _leaf(document, edit.key_path)
        if current is _MISSING:
            kind = ConflictKind.USER_REMOVED
        elif _same_value(current, edit.written):
            kind = ConflictKind.CLEAN
        else:
            kind = ConflictKind.USER_MODIFIED
        conflicts.append(KeyConflict(key_path=edit.key_path, kind=kind))
    return conflicts


def _classify_foreign(
    document: dict[str, JsonValue],
    patch: ConfigPatch,
    intended_edits: Sequence[JsonConfigEdit],
) -> list[KeyConflict]:
    """Flag intended keys we did not write that are already occupied on disk.

    A key is foreign when it was meant to be ours (in ``intended_edits``) but is
    absent from ``patch.edits`` — the apply skipped or was blocked — and the path
    is now occupied: either its leaf exists, or a parent along the way is a
    non-object that cannot hold our leaf.
    """
    owned = {edit.key_path for edit in patch.edits}
    foreign: list[KeyConflict] = []
    for edit in intended_edits:
        if edit.key_path in owned:
            continue
        current: object = document
        occupied = False
        for key in edit.key_path:
            if not isinstance(current, dict):
                occupied = True  # a non-object parent already holds this path
                break
            if key not in current:
                break
            current = current[key]
        else:
            occupied = True  # walked the whole path; the leaf itself exists
        if occupied:
            foreign.append(KeyConflict(key_path=edit.key_path, kind=ConflictKind.FOREIGN_PRESENT))
    return foreign


def reconcile_config_patch(
    patch: ConfigPatch,
    *,
    intended_edits: Sequence[JsonConfigEdit] | None = None,
) -> ConfigReconcileReport:
    """Classify a recorded owned patch against the file on disk now.

    Read-only. File-state problems are reported, never raised; only an invalid
    patch contract raises. ``intended_edits``, when supplied, lets the inspector
    flag a pre-existing registration the manager meant to own but never wrote.
    """
    patch = ConfigPatch.model_validate(patch.model_dump(warnings=False))

    def report(file_state: FileState, keys: tuple[KeyConflict, ...] = ()) -> ConfigReconcileReport:
        return ConfigReconcileReport(
            project_root=patch.project_root,
            relative_path=patch.relative_path,
            tool_id=patch.tool_id,
            file_state=file_state,
            keys=keys,
        )

    if not _supported(patch):
        return report(FileState.UNSUPPORTED)

    try:
        with patches._parent(patch.project_root, patch.relative_path) as (parent, name):
            raw, state = patches._read(parent, name, limit=4 * 1024 * 1024)
    except patches.ConfigurationConflict:
        # Unsupported shape, symlinked file, or a parent that is not a real
        # directory. Read-only: tell the caller, do not raise.
        return report(FileState.UNREADABLE)
    except FileNotFoundError:
        return report(FileState.MISSING)
    except OSError:
        return report(FileState.UNREADABLE)

    if not state.exists:
        return report(FileState.MISSING)

    try:
        document = _document(patch, raw)
    except patches.ConfigurationConflict:
        return report(FileState.UNREADABLE)

    file_state = FileState.READABLE if state == patch.written_file else FileState.STALE
    keys = _classify_owned(document, patch)
    if intended_edits is not None:
        keys.extend(_classify_foreign(document, patch, intended_edits))
    return report(file_state, tuple(keys))

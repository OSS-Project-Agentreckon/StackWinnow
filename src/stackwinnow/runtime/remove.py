"""Removal planning for exclusively managed resources.

Classifies every receipt-owned path as either a removal candidate or a
retained resource.  The plan is read-only — it never deletes anything.
Actual deletion is performed by the remove command (B07).

Classification rules, applied in order:
  1. Path not present on disk                      → RETAIN (nothing to delete)
  2. Path is outside the managed prefix            → RETAIN (external installation)
  3. Path is a symlink                             → RETAIN (unsafe alias)
  4. Path is shared infrastructure                 → RETAIN (.stackwinnow dir, receipts, lock)
  5. Path is designated project data               → RETAIN (results, graphs, reports, caches)
  6. Path is shared with a retained tool           → RETAIN (normalised comparison)
  7. Path is a directory containing retained files → RETAIN (containment)
  8. Path owned by a failed or interrupted step    → RETAIN (partial state)
  9. Otherwise                                     → REMOVE (exclusively owned managed resource)
"""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from stackwinnow.contracts import Contract, Identifier, NonEmptyText, UntrimmedText

if TYPE_CHECKING:
    from stackwinnow.installer import StepReceipt

_MANAGED_PREFIX = ".stackwinnow"
_RECEIPTS_FILE = "receipts.json"
_LOCK_FILE = "operation.lock"

# Directory name components within .stackwinnow/ that hold project data
# (evaluation results, relationship graphs, verification evidence) rather than
# installed software.  These survive tool removal so the user keeps their history.
_RETAINED_DATA_NAMES: frozenset[str] = frozenset({
    "results",
    "reports",
    "graphs",
    "output",
    "checks",
})


class RemovalAction(StrEnum):
    REMOVE = "remove"
    RETAIN = "retain"


class RemovalItem(Contract):
    """Classification of one owned path from a succeeded step receipt."""

    path: UntrimmedText
    tool_id: Identifier
    step_id: Identifier
    action: RemovalAction
    reason: NonEmptyText


class RemovalPlan(Contract):
    """Classified snapshot of receipt-owned paths for one project."""

    schema_version: Literal[1] = 1
    project_root: UntrimmedText
    items: list[RemovalItem] = Field(default_factory=list)

    @property
    def candidates(self) -> list[RemovalItem]:
        """Paths classified for deletion — exclusively owned managed resources."""
        return [i for i in self.items if i.action == RemovalAction.REMOVE]

    @property
    def retained(self) -> list[RemovalItem]:
        """Paths that must not be touched, with the reason for each."""
        return [i for i in self.items if i.action == RemovalAction.RETAIN]


def _resolve(raw: str, project_root: Path) -> Path:
    p = Path(raw)
    return p if p.is_absolute() else project_root / p


def _normalise(raw: str, project_root: Path) -> str:
    """Canonical resolved absolute string key for consistent path comparison.

    Using raw strings directly misses aliases: an absolute and a relative path
    can refer to the same resource and must compare equal.
    """
    abs_p = _resolve(raw, project_root)
    try:
        return str(abs_p.resolve())
    except OSError:
        return str(abs_p.absolute())


def _is_managed(path: Path, project_root: Path) -> bool:
    """True when path resolves strictly inside the managed .stackwinnow/ prefix."""
    try:
        path.resolve().relative_to((project_root / _MANAGED_PREFIX).resolve())
        return True
    except (ValueError, OSError):
        return False


def _is_infrastructure(path: Path, project_root: Path) -> bool:
    """True when path is shared infrastructure that must never be removed."""
    managed = project_root / _MANAGED_PREFIX
    try:
        resolved = path.resolve()
        return resolved in {
            managed.resolve(),
            (managed / _RECEIPTS_FILE).resolve(),
            (managed / _LOCK_FILE).resolve(),
        }
    except OSError:
        return False


def _is_project_data(norm_path: str, project_root: Path) -> bool:
    """True when path is project data (results, graphs) designated for retention."""
    try:
        managed = (project_root / _MANAGED_PREFIX).resolve()
        rel = Path(norm_path).relative_to(managed)
        return any(part in _RETAINED_DATA_NAMES for part in rel.parts)
    except (ValueError, OSError):
        return False


def plan_removal(
    project_root: str,
    tool_ids: list[str] | None = None,
) -> RemovalPlan:
    """Build a removal plan for the managed resources of a project.

    Parameters
    ----------
    project_root:
        Absolute path of the project being partially or fully uninstalled.
    tool_ids:
        Tools whose resources are considered for removal.  Pass ``None`` to
        include every tool that has a succeeded receipt.  Pass a subset to
        scope the plan to specific tools, leaving others' resources in place.

    Returns a :class:`RemovalPlan` classifying every owned path.  The plan
    is read-only — the caller decides when and whether to act on it.

    Raises :exc:`~stackwinnow.installer.InstallerError` when receipts are
    corrupt or belong to a different project root.
    """
    from stackwinnow.installer import OperationStatus, load_record

    record = load_record(project_root)
    root = Path(project_root)

    target_ids: set[str] | None = set(tool_ids) if tool_ids is not None else None

    # Collect receipts being removed and build a set of normalised paths that
    # must not be touched.  Retained paths come from two sources:
    #   (a) tools that are NOT in scope — their files are still in active use;
    #   (b) failed or interrupted steps — their partial state must not be removed.
    to_remove: list[StepReceipt] = []
    retained_norm: set[str] = set()

    for step in record.steps:
        if step.dry_run:
            continue
        in_scope = target_ids is None or step.tool_id in target_ids
        if step.status == OperationStatus.SUCCEEDED:
            if in_scope:
                to_remove.append(step)
            else:
                for raw in step.owned_paths:
                    retained_norm.add(_normalise(raw, root))
        else:
            # Failed/interrupted step: paths may be partial — protect them
            # regardless of whether the tool is in scope.
            for raw in step.owned_paths:
                retained_norm.add(_normalise(raw, root))

    items: list[RemovalItem] = []

    for receipt in to_remove:
        for raw in receipt.owned_paths:
            path = _resolve(raw, root)
            norm_key = _normalise(raw, root)

            if not path.exists():
                items.append(
                    RemovalItem(
                        path=raw,
                        tool_id=receipt.tool_id,
                        step_id=receipt.step_id,
                        action=RemovalAction.RETAIN,
                        reason="Path is not present on disk; nothing to remove.",
                    )
                )
                continue

            if path.is_symlink():
                items.append(
                    RemovalItem(
                        path=raw,
                        tool_id=receipt.tool_id,
                        step_id=receipt.step_id,
                        action=RemovalAction.RETAIN,
                        reason=(
                            "Path is a symlink; removing it automatically is unsafe. "
                            "Inspect and remove manually."
                        ),
                    )
                )
                continue

            if _is_infrastructure(path, root):
                items.append(
                    RemovalItem(
                        path=raw,
                        tool_id=receipt.tool_id,
                        step_id=receipt.step_id,
                        action=RemovalAction.RETAIN,
                        reason=(
                            "Path is shared infrastructure (.stackwinnow prefix, "
                            "receipts file, or operation lock); it must not be removed."
                        ),
                    )
                )
                continue

            if not _is_managed(path, root):
                items.append(
                    RemovalItem(
                        path=raw,
                        tool_id=receipt.tool_id,
                        step_id=receipt.step_id,
                        action=RemovalAction.RETAIN,
                        reason=(
                            "Path is outside the managed prefix; "
                            "treating as an external installation."
                        ),
                    )
                )
                continue

            if _is_project_data(norm_key, root):
                items.append(
                    RemovalItem(
                        path=raw,
                        tool_id=receipt.tool_id,
                        step_id=receipt.step_id,
                        action=RemovalAction.RETAIN,
                        reason=(
                            "Path holds project data (results, graphs, or reports) "
                            "designated for retention."
                        ),
                    )
                )
                continue

            if norm_key in retained_norm:
                items.append(
                    RemovalItem(
                        path=raw,
                        tool_id=receipt.tool_id,
                        step_id=receipt.step_id,
                        action=RemovalAction.RETAIN,
                        reason=(
                            "Path is also referenced by a tool that is not being removed; "
                            "retaining for shared use."
                        ),
                    )
                )
                continue

            # Containment: retain a directory that contains files owned by a
            # retained tool or recorded by a failed step.
            if path.is_dir() and any(
                rp.startswith(norm_key + os.sep) for rp in retained_norm
            ):
                items.append(
                    RemovalItem(
                        path=raw,
                        tool_id=receipt.tool_id,
                        step_id=receipt.step_id,
                        action=RemovalAction.RETAIN,
                        reason=(
                            "Directory contains files referenced by a retained tool "
                            "or recorded by a failed step."
                        ),
                    )
                )
                continue

            items.append(
                RemovalItem(
                    path=raw,
                    tool_id=receipt.tool_id,
                    step_id=receipt.step_id,
                    action=RemovalAction.REMOVE,
                    reason=(
                        f"Path is exclusively owned by '{receipt.tool_id}' "
                        "and within the managed prefix."
                    ),
                )
            )

    return RemovalPlan(project_root=project_root, items=items)

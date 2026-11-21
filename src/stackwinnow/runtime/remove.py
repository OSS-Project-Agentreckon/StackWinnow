"""Removal planning for exclusively managed resources.

Classifies every receipt-owned path as either a removal candidate or a
retained resource.  The plan is read-only — it never deletes anything.
Actual deletion is performed by the remove command (see step 21).

Classification rules, applied in order:
  1. Path not present on disk  → RETAIN  (nothing to delete)
  2. Path is outside the managed prefix (.stackwinnow/)  → RETAIN  (external install)
  3. Path is also referenced by a tool not being removed  → RETAIN  (shared use)
  4. Otherwise  → REMOVE  (exclusively owned managed resource)
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from stackwinnow.contracts import Contract, Identifier, NonEmptyText, UntrimmedText

if TYPE_CHECKING:
    from stackwinnow.installer import StepReceipt

_MANAGED_PREFIX = ".stackwinnow"
# The receipts file is shared state for the whole project; never a removal candidate.
_RECEIPTS_FILE = "receipts.json"


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


def _is_managed(path: Path, project_root: Path) -> bool:
    """True when path is strictly inside the managed .stackwinnow/ prefix."""
    try:
        path.resolve().relative_to((project_root / _MANAGED_PREFIX).resolve())
        return True
    except ValueError:
        return False


def _is_receipts_file(path: Path, project_root: Path) -> bool:
    receipts = (project_root / _MANAGED_PREFIX / _RECEIPTS_FILE).resolve()
    try:
        return path.resolve() == receipts
    except OSError:
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

    # Collect receipts being removed and those being kept separately.
    to_remove: list[StepReceipt] = []
    retained_paths: set[str] = set()

    for step in record.steps:
        if step.status != OperationStatus.SUCCEEDED or step.dry_run:
            continue
        if target_ids is None or step.tool_id in target_ids:
            to_remove.append(step)
        else:
            # This tool is not being removed; its owned paths are "in use".
            retained_paths.update(step.owned_paths)

    items: list[RemovalItem] = []

    for receipt in to_remove:
        for raw in receipt.owned_paths:
            path = _resolve(raw, root)

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

            # Always keep the receipts file — it is shared project state.
            if _is_receipts_file(path, root):
                items.append(
                    RemovalItem(
                        path=raw,
                        tool_id=receipt.tool_id,
                        step_id=receipt.step_id,
                        action=RemovalAction.RETAIN,
                        reason="Path is the shared receipts file; it must not be removed.",
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

            if raw in retained_paths:
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

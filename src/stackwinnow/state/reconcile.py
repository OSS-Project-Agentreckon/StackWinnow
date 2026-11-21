"""Receipt-based state reconciliation before rerunning installation plans.

Reconciliation runs after loading durable receipts but before any filesystem
writes or subprocess commands.  It answers one question per step:

  SKIP   — the step already succeeded and its owned paths are still present;
            no work is needed.
  RETRY  — the step failed, was interrupted, or its owned paths are missing
            despite a succeeded receipt (stale); running it again is safe.
  FRESH  — no meaningful prior receipt exists; treat the step as new.

The caller decides what to do with RETRY and FRESH steps.  The reconciler
never modifies the record, removes receipts, or touches the filesystem.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from stackwinnow.contracts import (
    Contract,
    Identifier,
    InstallPlan,
    NonEmptyText,
    OperationStatus,
    PlanStep,
)

if TYPE_CHECKING:
    from stackwinnow.installer import ExecutionRecord


class ReconcileAction(StrEnum):
    SKIP = "skip"
    RETRY = "retry"
    FRESH = "fresh"


class StepReconciliation(Contract):
    """Reconciliation verdict for one plan step."""

    step_id: Identifier
    tool_id: Identifier
    action: ReconcileAction
    message: NonEmptyText
    stale: bool = False


class ResumeReport(Contract):
    """Reconciliation results for every step in a plan."""

    schema_version: Literal[1] = 1
    project_root: NonEmptyText
    steps: list[StepReconciliation] = Field(default_factory=list)

    @property
    def all_skippable(self) -> bool:
        """True when every step is verified complete; applying would be a no-op."""
        return bool(self.steps) and all(s.action == ReconcileAction.SKIP for s in self.steps)

    @property
    def stale_steps(self) -> list[StepReconciliation]:
        """Steps whose receipts claim success but whose owned paths have disappeared."""
        return [s for s in self.steps if s.stale]


def reconcile_step(
    step: PlanStep,
    record: ExecutionRecord,
    project_root: str,
) -> StepReconciliation:
    """Classify one plan step based on its receipt and observed filesystem state.

    ``record`` is read-only; the function never modifies it.
    ``project_root`` is used only to resolve owned paths for stale-detection.
    """
    receipt = record.receipt_for(step.step_id)

    if receipt is None or receipt.dry_run or receipt.tool_id != step.tool_id:
        return StepReconciliation(
            step_id=step.step_id,
            tool_id=step.tool_id,
            action=ReconcileAction.FRESH,
            message="No prior attempt recorded for this step.",
        )

    if receipt.status == OperationStatus.SUCCEEDED:
        # Verify that at least one owned path still exists on disk.  A step that
        # wrote no owned paths (e.g. a config-only step) is trusted by receipt alone.
        if receipt.owned_paths and not any(Path(p).exists() for p in receipt.owned_paths):
            return StepReconciliation(
                step_id=step.step_id,
                tool_id=step.tool_id,
                action=ReconcileAction.RETRY,
                stale=True,
                message=(
                    f"Receipt records '{step.tool_id}' as installed but all owned paths "
                    "are missing; reinstalling to restore consistent state."
                ),
            )
        return StepReconciliation(
            step_id=step.step_id,
            tool_id=step.tool_id,
            action=ReconcileAction.SKIP,
            message=(f"Step '{step.step_id}' already completed and observed state is consistent."),
        )

    # FAILED or BLOCKED receipt — includes both interrupted-run intent markers and
    # genuine failures.  Both are safe to retry; the executor will overwrite the receipt.
    return StepReconciliation(
        step_id=step.step_id,
        tool_id=step.tool_id,
        action=ReconcileAction.RETRY,
        message=(
            f"Step '{step.step_id}' previously {receipt.status.value}; "
            f"retrying: {receipt.message[:120]}"
        ),
    )


def reconcile_plan(plan: InstallPlan) -> ResumeReport:
    """Reconcile every step in *plan* against its durable execution record.

    Loads the record from disk.  Raises :exc:`~stackwinnow.installer.InstallerError`
    when receipts are corrupt or belong to a different project.
    """
    from stackwinnow.installer import load_record  # deferred — avoids circular import

    record = load_record(plan.project_root)
    return ResumeReport(
        project_root=plan.project_root,
        steps=[reconcile_step(step, record, plan.project_root) for step in plan.steps],
    )

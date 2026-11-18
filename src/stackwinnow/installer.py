"""Execute installation plans and persist durable step receipts.

Receipts are written after each step so interrupted runs leave the project
in an understandable state. Dry runs never touch the filesystem.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from stackwinnow.contracts import (
    Contract,
    Identifier,
    InstallPlan,
    NonEmptyText,
    OperationResult,
    OperationStatus,
    PlanStep,
)

_STATE_DIR = ".stackwinnow"
_RECEIPTS_FILE = "receipts.json"

StepRunner = Callable[[PlanStep], OperationResult]


class StepReceipt(Contract):
    """Durable record of one attempted installation step."""

    schema_version: Literal[1] = 1
    step_id: Identifier
    tool_id: Identifier
    status: OperationStatus
    message: NonEmptyText
    timestamp: NonEmptyText  # ISO 8601 UTC
    dry_run: bool = False
    errors: list[NonEmptyText] = Field(default_factory=list)
    owned_paths: list[NonEmptyText] = Field(default_factory=list)


class ExecutionRecord(Contract):
    """All step receipts for one project root."""

    schema_version: Literal[1] = 1
    project_root: NonEmptyText
    steps: list[StepReceipt] = Field(default_factory=list)

    def receipt_for(self, step_id: str) -> StepReceipt | None:
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None

    def is_succeeded(self, step_id: str) -> bool:
        """True only when a real (non-dry) run recorded success for this step."""
        receipt = self.receipt_for(step_id)
        return (
            receipt is not None
            and receipt.status == OperationStatus.SUCCEEDED
            and not receipt.dry_run
        )


def _receipts_path(project_root: str) -> Path:
    return Path(project_root) / _STATE_DIR / _RECEIPTS_FILE


def load_record(project_root: str) -> ExecutionRecord:
    """Load saved receipts, or return a fresh empty record."""
    path = _receipts_path(project_root)
    if path.exists():
        try:
            return ExecutionRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return ExecutionRecord(project_root=project_root)


def _persist(record: ExecutionRecord) -> None:
    """Write receipts to disk, creating the state directory if needed."""
    path = _receipts_path(record.project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.model_dump_json(indent=2), encoding="utf-8")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _record_step(record: ExecutionRecord, receipt: StepReceipt) -> None:
    """Replace any previous receipt for this step, then append the new one."""
    record.steps = [s for s in record.steps if s.step_id != receipt.step_id]
    record.steps.append(receipt)


def execute_plan(
    plan: InstallPlan,
    *,
    dry_run: bool = False,
    step_runner: StepRunner | None = None,
) -> tuple[ExecutionRecord, list[OperationResult]]:
    """Execute each step in order, persisting a receipt after every real step.

    - dry_run=True: no step_runner is called and nothing is written to disk.
    - step_runner=None and not dry_run: steps are recorded as BLOCKED.
    - Already-succeeded steps (from a prior real run) are skipped.
    """
    record = load_record(plan.project_root)
    results: list[OperationResult] = []

    for step in plan.steps:
        if record.is_succeeded(step.step_id):
            result = OperationResult(
                status=OperationStatus.SKIPPED,
                message=f"Step '{step.step_id}' already completed in a previous run.",
                tool_id=step.tool_id,
                step_id=step.step_id,
            )
            results.append(result)
            continue

        if dry_run:
            result = OperationResult(
                status=OperationStatus.SKIPPED,
                message=f"Dry run: would execute — {step.description}",
                tool_id=step.tool_id,
                step_id=step.step_id,
            )
            results.append(result)
            continue

        if step_runner is not None:
            raw = step_runner(step)
            result = OperationResult(
                status=raw.status,
                message=raw.message,
                tool_id=step.tool_id,
                step_id=step.step_id,
                errors=raw.errors,
                evidence=raw.evidence,
            )
        else:
            result = OperationResult(
                status=OperationStatus.BLOCKED,
                message=f"No runner registered for step '{step.step_id}'.",
                tool_id=step.tool_id,
                step_id=step.step_id,
                errors=["Register a step runner before executing plans."],
            )

        receipt = StepReceipt(
            step_id=step.step_id,
            tool_id=step.tool_id,
            status=result.status,
            message=result.message,
            timestamp=_now(),
            dry_run=False,
            errors=result.errors,
        )
        _record_step(record, receipt)
        _persist(record)
        results.append(result)

    return record, results

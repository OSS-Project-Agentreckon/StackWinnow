"""Tests for installation plan execution and receipt persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from stackwinnow.contracts import InstallPlan, OperationResult, OperationStatus, PlanStep
from stackwinnow.installer import (
    ExecutionRecord,
    StepReceipt,
    _receipts_path,
    execute_plan,
    load_record,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STEP_A = {"step_id": "install-headroom", "tool_id": "headroom", "description": "Install Headroom"}
STEP_B = {"step_id": "configure-headroom", "tool_id": "headroom", "description": "Configure Headroom"}


def _plan(project_root: str, steps: list[dict] | None = None) -> InstallPlan:
    steps = steps or [STEP_A]
    return InstallPlan(
        project_root=project_root,
        tool_ids=["headroom"],
        steps=steps,
    )


def _success_runner(step: PlanStep) -> OperationResult:
    return OperationResult(status=OperationStatus.SUCCEEDED, message=f"Installed {step.tool_id}.")


def _failure_runner(step: PlanStep) -> OperationResult:
    return OperationResult(
        status=OperationStatus.FAILED,
        message=f"Failed to install {step.tool_id}.",
        errors=["Package not found."],
    )


# ---------------------------------------------------------------------------
# Dry run — no filesystem changes
# ---------------------------------------------------------------------------


def test_dry_run_creates_no_files(tmp_path: Path) -> None:
    execute_plan(_plan(str(tmp_path)), dry_run=True, step_runner=_success_runner)
    assert not _receipts_path(str(tmp_path)).exists()


def test_dry_run_creates_no_state_directory(tmp_path: Path) -> None:
    execute_plan(_plan(str(tmp_path)), dry_run=True, step_runner=_success_runner)
    assert not (tmp_path / ".stackwinnow").exists()


def test_dry_run_returns_skipped_results(tmp_path: Path) -> None:
    _, results = execute_plan(_plan(str(tmp_path)), dry_run=True, step_runner=_success_runner)
    assert len(results) == 1
    assert results[0].status == OperationStatus.SKIPPED
    assert "Dry run" in results[0].message


def test_dry_run_does_not_call_step_runner(tmp_path: Path) -> None:
    called = []

    def tracking_runner(step: PlanStep) -> OperationResult:
        called.append(step.step_id)
        return _success_runner(step)

    execute_plan(_plan(str(tmp_path)), dry_run=True, step_runner=tracking_runner)
    assert called == []


# ---------------------------------------------------------------------------
# Real run — receipt persistence
# ---------------------------------------------------------------------------


def test_successful_run_persists_receipt(tmp_path: Path) -> None:
    execute_plan(_plan(str(tmp_path)), step_runner=_success_runner)
    assert _receipts_path(str(tmp_path)).exists()


def test_receipt_records_correct_status(tmp_path: Path) -> None:
    execute_plan(_plan(str(tmp_path)), step_runner=_success_runner)
    record = load_record(str(tmp_path))
    receipt = record.receipt_for("install-headroom")
    assert receipt is not None
    assert receipt.status == OperationStatus.SUCCEEDED
    assert receipt.tool_id == "headroom"
    assert receipt.dry_run is False


def test_failed_step_receipt_includes_errors(tmp_path: Path) -> None:
    execute_plan(_plan(str(tmp_path)), step_runner=_failure_runner)
    record = load_record(str(tmp_path))
    receipt = record.receipt_for("install-headroom")
    assert receipt is not None
    assert receipt.status == OperationStatus.FAILED
    assert receipt.errors


def test_receipt_has_timestamp(tmp_path: Path) -> None:
    execute_plan(_plan(str(tmp_path)), step_runner=_success_runner)
    record = load_record(str(tmp_path))
    receipt = record.receipt_for("install-headroom")
    assert receipt is not None
    assert "T" in receipt.timestamp  # ISO 8601 format


def test_receipt_persists_across_reload(tmp_path: Path) -> None:
    execute_plan(_plan(str(tmp_path)), step_runner=_success_runner)
    reloaded = load_record(str(tmp_path))
    assert reloaded.is_succeeded("install-headroom")


# ---------------------------------------------------------------------------
# No runner — blocked result
# ---------------------------------------------------------------------------


def test_no_runner_returns_blocked(tmp_path: Path) -> None:
    _, results = execute_plan(_plan(str(tmp_path)))
    assert results[0].status == OperationStatus.BLOCKED
    assert results[0].errors


def test_no_runner_still_persists_receipt(tmp_path: Path) -> None:
    execute_plan(_plan(str(tmp_path)))
    record = load_record(str(tmp_path))
    assert record.receipt_for("install-headroom") is not None


# ---------------------------------------------------------------------------
# Idempotency — already-succeeded steps are skipped
# ---------------------------------------------------------------------------


def test_already_succeeded_step_is_skipped(tmp_path: Path) -> None:
    execute_plan(_plan(str(tmp_path)), step_runner=_success_runner)
    _, results = execute_plan(_plan(str(tmp_path)), step_runner=_success_runner)
    assert results[0].status == OperationStatus.SKIPPED
    assert "already completed" in results[0].message


def test_skipped_step_does_not_overwrite_receipt(tmp_path: Path) -> None:
    execute_plan(_plan(str(tmp_path)), step_runner=_success_runner)
    first_ts = load_record(str(tmp_path)).receipt_for("install-headroom").timestamp
    execute_plan(_plan(str(tmp_path)), step_runner=_success_runner)
    second_ts = load_record(str(tmp_path)).receipt_for("install-headroom").timestamp
    assert first_ts == second_ts


def test_failed_step_is_not_skipped_on_retry(tmp_path: Path) -> None:
    execute_plan(_plan(str(tmp_path)), step_runner=_failure_runner)
    _, results = execute_plan(_plan(str(tmp_path)), step_runner=_success_runner)
    assert results[0].status == OperationStatus.SUCCEEDED


# ---------------------------------------------------------------------------
# Multi-step plans and partial execution
# ---------------------------------------------------------------------------


def test_multi_step_plan_all_succeed(tmp_path: Path) -> None:
    plan = _plan(str(tmp_path), steps=[STEP_A, STEP_B])
    _, results = execute_plan(plan, step_runner=_success_runner)
    assert len(results) == 2
    assert all(r.status == OperationStatus.SUCCEEDED for r in results)


def test_interrupted_plan_leaves_readable_receipts(tmp_path: Path) -> None:
    """Simulate interruption: first step succeeds, second raises mid-execution."""
    call_count = 0

    def partial_runner(step: PlanStep) -> OperationResult:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("Simulated interruption")
        return _success_runner(step)

    plan = _plan(str(tmp_path), steps=[STEP_A, STEP_B])
    with pytest.raises(RuntimeError):
        execute_plan(plan, step_runner=partial_runner)

    record = load_record(str(tmp_path))
    assert record.is_succeeded("install-headroom")
    assert record.receipt_for("configure-headroom") is None


def test_resume_after_interruption_skips_completed_step(tmp_path: Path) -> None:
    call_count = 0

    def partial_runner(step: PlanStep) -> OperationResult:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("Simulated interruption")
        return _success_runner(step)

    plan = _plan(str(tmp_path), steps=[STEP_A, STEP_B])
    with pytest.raises(RuntimeError):
        execute_plan(plan, step_runner=partial_runner)

    _, results = execute_plan(plan, step_runner=_success_runner)
    assert results[0].status == OperationStatus.SKIPPED
    assert results[1].status == OperationStatus.SUCCEEDED


# ---------------------------------------------------------------------------
# load_record — corrupt or missing files
# ---------------------------------------------------------------------------


def test_load_record_returns_empty_when_no_file(tmp_path: Path) -> None:
    record = load_record(str(tmp_path))
    assert record.steps == []
    assert record.project_root == str(tmp_path)


def test_load_record_returns_empty_on_corrupt_file(tmp_path: Path) -> None:
    receipts = _receipts_path(str(tmp_path))
    receipts.parent.mkdir(parents=True)
    receipts.write_text("not valid json", encoding="utf-8")
    record = load_record(str(tmp_path))
    assert record.steps == []


# ---------------------------------------------------------------------------
# Result fields are always set correctly
# ---------------------------------------------------------------------------


def test_result_carries_step_and_tool_ids(tmp_path: Path) -> None:
    _, results = execute_plan(_plan(str(tmp_path)), step_runner=_success_runner)
    assert results[0].step_id == "install-headroom"
    assert results[0].tool_id == "headroom"


def test_empty_plan_returns_no_results(tmp_path: Path) -> None:
    plan = InstallPlan(project_root=str(tmp_path), tool_ids=[], steps=[])
    _, results = execute_plan(plan, step_runner=_success_runner)
    assert results == []

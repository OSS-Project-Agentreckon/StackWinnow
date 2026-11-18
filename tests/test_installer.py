"""Tests for installation plan execution and receipt persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from stackwinnow.contracts import InstallPlan, OperationStatus, PlanStep
from stackwinnow.installer import (
    _STATE_DIR,
    InstallerError,
    RunnerOutcome,
    _receipts_path,
    execute_plan,
    load_record,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STEP_A = {"step_id": "install-headroom", "tool_id": "headroom", "description": "Install Headroom"}
STEP_B = {
    "step_id": "configure-headroom",
    "tool_id": "headroom",
    "description": "Configure Headroom",
}
STEP_GRAPHIFY = {
    "step_id": "install-headroom",
    "tool_id": "graphify",
    "description": "Install Graphify (same step_id as STEP_A, different tool)",
}


def _plan(project_root: str, steps: list[dict] | None = None) -> InstallPlan:
    steps = steps or [STEP_A]
    return InstallPlan(
        project_root=project_root,
        tool_ids=["headroom"],
        steps=steps,
    )


def _success_runner(step: PlanStep) -> RunnerOutcome:
    return RunnerOutcome(status=OperationStatus.SUCCEEDED, message=f"Installed {step.tool_id}.")


def _failure_runner(step: PlanStep) -> RunnerOutcome:
    return RunnerOutcome(
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

    def tracking_runner(step: PlanStep) -> RunnerOutcome:
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
    assert reloaded.is_succeeded("install-headroom", "headroom")


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
# Idempotency — same step_id but different tool_id is NOT skipped  (finding 6)
# ---------------------------------------------------------------------------


def test_same_step_id_different_tool_is_not_skipped(tmp_path: Path) -> None:
    """A receipt for 'install-headroom' must not gate a different tool with the same step_id."""
    execute_plan(_plan(str(tmp_path)), step_runner=_success_runner)

    plan_b = InstallPlan(
        project_root=str(tmp_path),
        tool_ids=["graphify"],
        steps=[STEP_GRAPHIFY],
    )
    _, results = execute_plan(plan_b, step_runner=_success_runner)
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

    def partial_runner(step: PlanStep) -> RunnerOutcome:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("Simulated interruption")
        return _success_runner(step)

    plan = _plan(str(tmp_path), steps=[STEP_A, STEP_B])
    with pytest.raises(RuntimeError):
        execute_plan(plan, step_runner=partial_runner)

    record = load_record(str(tmp_path))
    assert record.is_succeeded("install-headroom", "headroom")
    # Intent receipt written before the runner crashed — step is not silently missing.
    intent = record.receipt_for("configure-headroom")
    assert intent is not None
    assert intent.status == OperationStatus.FAILED


def test_resume_after_interruption_skips_completed_step(tmp_path: Path) -> None:
    call_count = 0

    def partial_runner(step: PlanStep) -> RunnerOutcome:
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
# Failure stops downstream steps  (finding 4)
# ---------------------------------------------------------------------------


def test_failed_step_prevents_downstream_execution(tmp_path: Path) -> None:
    """A FAILED step must prevent subsequent steps from being invoked."""
    plan = _plan(str(tmp_path), steps=[STEP_A, STEP_B])
    side_effects: list[str] = []

    def tracking_runner(step: PlanStep) -> RunnerOutcome:
        side_effects.append(step.step_id)
        if step.step_id == "install-headroom":
            return RunnerOutcome(
                status=OperationStatus.FAILED, message="Install failed.", errors=["Error"]
            )
        return RunnerOutcome(status=OperationStatus.SUCCEEDED, message="OK.")

    _, results = execute_plan(plan, step_runner=tracking_runner)

    assert side_effects == ["install-headroom"], "configure-headroom runner must never be called"
    assert results[0].status == OperationStatus.FAILED
    assert results[1].status == OperationStatus.SKIPPED
    assert "not executed" in results[1].message


# ---------------------------------------------------------------------------
# Intent receipt before runner is invoked  (finding 5)
# ---------------------------------------------------------------------------


def test_intent_receipt_persisted_before_runner_crashes(tmp_path: Path) -> None:
    """An interrupted runner must leave a FAILED intent receipt, not silent state."""
    artifact = tmp_path / "artifact.txt"

    def crashing_runner(step: PlanStep) -> RunnerOutcome:
        artifact.write_text("created by runner")  # side effect before crash
        raise RuntimeError("runner crashed after creating artifact")

    with pytest.raises(RuntimeError):
        execute_plan(_plan(str(tmp_path)), step_runner=crashing_runner)

    assert artifact.exists(), "side effect happened"
    record = load_record(str(tmp_path))
    receipt = record.receipt_for("install-headroom")
    assert receipt is not None, "intent receipt must be on disk after crash"
    assert receipt.status == OperationStatus.FAILED


# ---------------------------------------------------------------------------
# Owned paths carried from runner into receipt  (finding 7)
# ---------------------------------------------------------------------------


def test_owned_paths_from_runner_persisted_in_receipt(tmp_path: Path) -> None:
    config = str(tmp_path / "config.yaml")

    def owning_runner(step: PlanStep) -> RunnerOutcome:
        return RunnerOutcome(
            status=OperationStatus.SUCCEEDED,
            message="Installed.",
            owned_paths=[config],
        )

    execute_plan(_plan(str(tmp_path)), step_runner=owning_runner)
    record = load_record(str(tmp_path))
    receipt = record.receipt_for("install-headroom")
    assert receipt is not None
    assert config in receipt.owned_paths


# ---------------------------------------------------------------------------
# load_record — corrupt or missing files
# ---------------------------------------------------------------------------


def test_load_record_returns_empty_when_no_file(tmp_path: Path) -> None:
    record = load_record(str(tmp_path))
    assert record.steps == []
    assert record.project_root == str(tmp_path)


def test_load_record_raises_on_corrupt_file(tmp_path: Path) -> None:
    """Corrupt receipts must raise InstallerError; the file must be left intact."""
    receipts = _receipts_path(str(tmp_path))
    receipts.parent.mkdir(parents=True)
    original = b"not valid json"
    receipts.write_bytes(original)

    with pytest.raises(InstallerError, match="corrupt"):
        load_record(str(tmp_path))

    assert receipts.read_bytes() == original, "corrupt file must be preserved for recovery"


def test_execute_plan_raises_on_corrupt_receipts_without_calling_runner(tmp_path: Path) -> None:
    receipts = _receipts_path(str(tmp_path))
    receipts.parent.mkdir(parents=True)
    receipts.write_text("not valid json", encoding="utf-8")
    called: list[str] = []

    def tracking_runner(step: PlanStep) -> RunnerOutcome:
        called.append(step.step_id)
        return _success_runner(step)

    with pytest.raises(InstallerError):
        execute_plan(_plan(str(tmp_path)), step_runner=tracking_runner)

    assert called == [], "runner must not be called when receipts are corrupt"


# ---------------------------------------------------------------------------
# Path safety — symlinks and project root mismatch  (finding 1)
# ---------------------------------------------------------------------------


def test_symlinked_state_directory_is_rejected(tmp_path: Path) -> None:
    """Writing state into a symlinked directory must raise InstallerError."""
    real_dir = tmp_path / "real_state"
    real_dir.mkdir()
    state_dir = tmp_path / _STATE_DIR
    state_dir.symlink_to(real_dir)

    with pytest.raises(InstallerError, match="symlink"):
        execute_plan(_plan(str(tmp_path)), step_runner=_success_runner)


def test_project_root_mismatch_raises_on_load(tmp_path: Path) -> None:
    """Receipts written for project A must not silently pass validation for project B."""
    project_a = tmp_path / "project_a"
    project_b = tmp_path / "project_b"
    project_a.mkdir()
    project_b.mkdir()

    execute_plan(_plan(str(project_a)), step_runner=_success_runner)

    # Copy project_a receipts into project_b state directory
    receipts_a = _receipts_path(str(project_a))
    receipts_b_dir = project_b / _STATE_DIR
    receipts_b_dir.mkdir()
    (receipts_b_dir / "receipts.json").write_bytes(receipts_a.read_bytes())

    with pytest.raises(InstallerError, match="project root"):
        load_record(str(project_b))


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

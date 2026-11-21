"""Acceptance tests for state reconciliation and repeat-apply behaviour.

Covers the three guarantees of step 17:
  1. Apply twice creates no duplicate work (already-succeeded steps are skipped).
  2. A controlled interruption can resume (intent/failed receipts are retried).
  3. A stale receipt cannot mask a missing tool (owned paths gone → re-run).

Also covers the shared project lock that serialises concurrent operations.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stackwinnow.contracts import InstallPlan, OperationStatus, PlanStep
from stackwinnow.installer import (
    RunnerOutcome,
    execute_plan,
)
from stackwinnow.state import (
    ProjectLockError,
    ReconcileAction,
    project_lock,
    reconcile_plan,
)

# ---------------------------------------------------------------------------
# Helpers shared across all tests
# ---------------------------------------------------------------------------

_STEP = {"step_id": "tool-run-install", "tool_id": "tool-a", "description": "Install tool-a."}
_STEP_B = {"step_id": "tool-run-compress", "tool_id": "tool-a", "description": "Compress verify."}


def _plan(root: str | Path, steps: list[dict] | None = None) -> InstallPlan:
    steps = steps or [_STEP]
    return InstallPlan(
        project_root=str(root),
        tool_ids=["tool-a"],
        steps=steps,
    )


def _write_succeeded_receipt(root: Path, step: dict, owned_paths: list[str] | None = None) -> None:
    """Seed a succeeded receipt via execute_plan."""
    execute_plan(
        _plan(root, steps=[step]),
        step_runner=lambda s: RunnerOutcome(
            status=OperationStatus.SUCCEEDED,
            message="Pre-seeded succeeded receipt.",
            owned_paths=owned_paths or [],
        ),
    )


def _write_failed_receipt(
    root: Path,
    step: dict,
    message: str = "Step execution began but did not complete.",
) -> None:
    """Seed a failed receipt via execute_plan."""
    execute_plan(
        _plan(root, steps=[step]),
        step_runner=lambda s: RunnerOutcome(status=OperationStatus.FAILED, message=message),
    )


# ---------------------------------------------------------------------------
# 1. Apply twice — no duplicate work
# ---------------------------------------------------------------------------


def test_second_apply_skips_already_succeeded_steps(tmp_path):
    """A step that succeeded is skipped on the second apply."""
    plan = _plan(tmp_path)
    calls: list[str] = []

    def counting_runner(step: PlanStep) -> RunnerOutcome:
        calls.append(step.step_id)
        return RunnerOutcome(status=OperationStatus.SUCCEEDED, message="ok")

    execute_plan(plan, step_runner=counting_runner)
    assert len(calls) == 1

    execute_plan(plan, step_runner=counting_runner)
    assert len(calls) == 1, "Step should not run a second time after succeeding."


def test_second_apply_returns_skipped_result(tmp_path):
    """The second apply reports SKIPPED (not SUCCEEDED) for already-done steps."""
    plan = _plan(tmp_path)
    calls: list[str] = []

    def counting_runner(step: PlanStep) -> RunnerOutcome:
        calls.append(step.step_id)
        return RunnerOutcome(status=OperationStatus.SUCCEEDED, message="ok")

    _, first_results = execute_plan(plan, step_runner=counting_runner)
    _, second_results = execute_plan(plan, step_runner=counting_runner)

    assert first_results[0].status == OperationStatus.SUCCEEDED
    assert second_results[0].status == OperationStatus.SKIPPED


# ---------------------------------------------------------------------------
# 2. Controlled interruption — resume after failure
# ---------------------------------------------------------------------------


def test_failed_step_is_retried_on_next_apply(tmp_path):
    """A step with a FAILED receipt is re-executed on the next apply call."""
    plan = _plan(tmp_path)
    _write_failed_receipt(tmp_path, _STEP)

    calls: list[str] = []

    def counting_runner(step: PlanStep) -> RunnerOutcome:
        calls.append(step.step_id)
        return RunnerOutcome(status=OperationStatus.SUCCEEDED, message="ok")

    execute_plan(plan, step_runner=counting_runner)
    assert len(calls) == 1, "Step should be retried after a FAILED receipt."


def test_intent_receipt_is_retried_on_next_apply(tmp_path):
    """A step interrupted mid-run (intent marker) can be resumed."""
    plan = _plan(tmp_path)
    _write_failed_receipt(tmp_path, _STEP, message="Step execution began but did not complete.")

    calls: list[str] = []

    def counting_runner(step: PlanStep) -> RunnerOutcome:
        calls.append(step.step_id)
        return RunnerOutcome(status=OperationStatus.SUCCEEDED, message="ok")

    execute_plan(plan, step_runner=counting_runner)
    assert len(calls) == 1


def test_two_step_plan_resumes_from_failed_first_step(tmp_path):
    """A two-step plan where the first step was interrupted restarts only that step."""
    plan = _plan(tmp_path, steps=[_STEP, _STEP_B])
    _write_failed_receipt(tmp_path, _STEP)

    executed: list[str] = []

    def runner(step: PlanStep) -> RunnerOutcome:
        executed.append(step.step_id)
        return RunnerOutcome(status=OperationStatus.SUCCEEDED, message="ok")

    execute_plan(plan, step_runner=runner)
    assert executed == [_STEP["step_id"], _STEP_B["step_id"]]


# ---------------------------------------------------------------------------
# 3. Stale receipt — owned paths missing
# ---------------------------------------------------------------------------


def test_stale_receipt_does_not_silently_skip_step(tmp_path):
    """A succeeded receipt whose owned path no longer exists triggers a re-run."""
    vanished = str(tmp_path / ".stackwinnow" / "envs" / "tool-a" / "python")
    _write_succeeded_receipt(tmp_path, _STEP, owned_paths=[vanished])

    calls: list[str] = []

    def counting_runner(step: PlanStep) -> RunnerOutcome:
        calls.append(step.step_id)
        return RunnerOutcome(status=OperationStatus.SUCCEEDED, message="ok")

    execute_plan(_plan(tmp_path), step_runner=counting_runner)
    assert len(calls) == 1, "Stale receipt should cause the step to be re-run."


def test_succeeded_receipt_with_present_paths_skips_step(tmp_path):
    """A succeeded receipt whose owned path still exists on disk causes a skip."""
    owned = tmp_path / ".stackwinnow" / "envs" / "tool-a" / "python"
    owned.mkdir(parents=True)
    _write_succeeded_receipt(tmp_path, _STEP, owned_paths=[str(owned)])

    calls: list[str] = []

    def counting_runner(step: PlanStep) -> RunnerOutcome:
        calls.append(step.step_id)
        return RunnerOutcome(status=OperationStatus.SUCCEEDED, message="ok")

    execute_plan(_plan(tmp_path), step_runner=counting_runner)
    assert len(calls) == 0, "Valid receipt should skip the step."


def test_succeeded_receipt_without_owned_paths_skips_step(tmp_path):
    """Config-only steps (no owned paths) are trusted by receipt alone."""
    _write_succeeded_receipt(tmp_path, _STEP, owned_paths=[])

    calls: list[str] = []

    def counting_runner(step: PlanStep) -> RunnerOutcome:
        calls.append(step.step_id)
        return RunnerOutcome(status=OperationStatus.SUCCEEDED, message="ok")

    execute_plan(_plan(tmp_path), step_runner=counting_runner)
    assert len(calls) == 0, "No-owned-paths receipt should skip (config-only step)."


# ---------------------------------------------------------------------------
# 4. Concurrent serialisation — project lock
# ---------------------------------------------------------------------------


def test_project_lock_blocks_concurrent_acquire(tmp_path):
    """A second caller on the same root receives ProjectLockError immediately."""
    with project_lock(tmp_path):
        with pytest.raises(ProjectLockError):
            with project_lock(tmp_path):
                pass


def test_project_lock_releases_after_body_completes(tmp_path):
    """The lock file is removed after a normal exit so a subsequent caller can proceed."""
    with project_lock(tmp_path):
        pass
    with project_lock(tmp_path):
        pass  # should not raise


def test_project_lock_releases_after_exception(tmp_path):
    """The lock file is removed even when the body raises."""
    with pytest.raises(RuntimeError):
        with project_lock(tmp_path):
            raise RuntimeError("body failed")
    with project_lock(tmp_path):
        pass  # should not raise


def test_project_lock_rejects_symlink(tmp_path):
    """A symlink at the lock path is rejected before acquire."""
    managed = tmp_path / ".stackwinnow"
    managed.mkdir()
    lock_path = managed / "operation.lock"
    target = tmp_path / "elsewhere"
    target.touch()
    lock_path.symlink_to(target)
    with pytest.raises(ProjectLockError, match="symlink"):
        with project_lock(tmp_path):
            pass


# ---------------------------------------------------------------------------
# 5. reconcile_step and reconcile_plan contracts
# ---------------------------------------------------------------------------


def test_reconcile_fresh_when_no_receipt(tmp_path):
    plan = _plan(tmp_path)
    report = reconcile_plan(plan)
    assert len(report.steps) == 1
    assert report.steps[0].action == ReconcileAction.FRESH
    assert not report.all_skippable


def test_reconcile_skip_when_succeeded_with_present_path(tmp_path):
    owned = tmp_path / ".stackwinnow" / "envs" / "tool-a" / "python"
    owned.mkdir(parents=True)
    _write_succeeded_receipt(tmp_path, _STEP, owned_paths=[str(owned)])
    report = reconcile_plan(_plan(tmp_path))
    assert report.steps[0].action == ReconcileAction.SKIP
    assert report.all_skippable
    assert report.stale_steps == []


def test_reconcile_retry_stale_when_owned_path_missing(tmp_path):
    vanished = str(tmp_path / ".stackwinnow" / "envs" / "tool-a" / "python")
    _write_succeeded_receipt(tmp_path, _STEP, owned_paths=[vanished])
    report = reconcile_plan(_plan(tmp_path))
    step = report.steps[0]
    assert step.action == ReconcileAction.RETRY
    assert step.stale
    assert report.stale_steps == [step]
    assert not report.all_skippable


def test_reconcile_retry_when_failed_receipt(tmp_path):
    _write_failed_receipt(tmp_path, _STEP)
    report = reconcile_plan(_plan(tmp_path))
    assert report.steps[0].action == ReconcileAction.RETRY
    assert not report.steps[0].stale


def test_reconcile_plan_all_skippable_only_when_all_skip(tmp_path):
    """all_skippable is False for an empty plan and False when any step is non-SKIP."""
    empty_plan = InstallPlan(project_root=str(tmp_path), tool_ids=[], steps=[])
    empty_report = reconcile_plan(empty_plan)
    assert not empty_report.all_skippable

    # Two-step plan where only one has a succeeded receipt with present path.
    owned = tmp_path / ".stackwinnow" / "envs" / "tool-a" / "python"
    owned.mkdir(parents=True)
    _write_succeeded_receipt(tmp_path, _STEP, owned_paths=[str(owned)])
    report = reconcile_plan(_plan(tmp_path, steps=[_STEP, _STEP_B]))
    assert not report.all_skippable

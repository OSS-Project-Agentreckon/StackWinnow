"""Acceptance tests for managed-resource removal planning (step 20).

Verifies the four classification rules:
  1. Absent paths → RETAIN (nothing to delete).
  2. External paths (outside .stackwinnow/) → RETAIN.
  3. Paths shared with a retained tool → RETAIN.
  4. Exclusively managed paths → REMOVE.

Also covers tool_ids scoping, failed-receipt exclusion, and the receipts-file
protection guard.
"""

from __future__ import annotations

from pathlib import Path

from stackwinnow.contracts import InstallPlan, OperationStatus
from stackwinnow.installer import RunnerOutcome, execute_plan
from stackwinnow.runtime.remove import RemovalAction, RemovalPlan, plan_removal

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_STEP_A = {"step_id": "tool-a-install", "tool_id": "tool-a", "description": "Install tool-a."}
_STEP_B = {"step_id": "tool-b-install", "tool_id": "tool-b", "description": "Install tool-b."}


def _plan(root: str | Path, steps: list[dict]) -> InstallPlan:
    tool_ids = list(dict.fromkeys(s["tool_id"] for s in steps))
    return InstallPlan(project_root=str(root), tool_ids=tool_ids, steps=steps)


def _run(root: Path, step: dict, owned_paths: list[str] | None = None) -> None:
    """Seed a succeeded receipt via execute_plan."""
    execute_plan(
        _plan(root, [step]),
        step_runner=lambda s: RunnerOutcome(
            status=OperationStatus.SUCCEEDED,
            message="ok",
            owned_paths=owned_paths or [],
        ),
    )


def _run_failed(root: Path, step: dict, owned_paths: list[str] | None = None) -> None:
    """Seed a failed receipt via execute_plan."""
    execute_plan(
        _plan(root, [step]),
        step_runner=lambda s: RunnerOutcome(
            status=OperationStatus.FAILED,
            message="failed",
            owned_paths=owned_paths or [],
        ),
    )


# ---------------------------------------------------------------------------
# 1. Absent path → RETAIN
# ---------------------------------------------------------------------------


def test_absent_path_is_retained(tmp_path):
    """An owned path that no longer exists on disk is retained (nothing to delete)."""
    gone = str(tmp_path / ".stackwinnow" / "envs" / "tool-a" / "python")
    _run(tmp_path, _STEP_A, owned_paths=[gone])

    plan = plan_removal(str(tmp_path))

    assert len(plan.items) == 1
    item = plan.items[0]
    assert item.action == RemovalAction.RETAIN
    assert "not present" in item.reason


# ---------------------------------------------------------------------------
# 2. External path → RETAIN
# ---------------------------------------------------------------------------


def test_external_path_is_retained(tmp_path):
    """A path outside .stackwinnow/ is an external installation and must not be touched."""
    external = tmp_path / "external_tool"
    external.mkdir()
    _run(tmp_path, _STEP_A, owned_paths=[str(external)])

    plan = plan_removal(str(tmp_path))

    assert len(plan.items) == 1
    assert plan.items[0].action == RemovalAction.RETAIN
    assert "external" in plan.items[0].reason.lower()


def test_path_in_sibling_directory_is_external(tmp_path):
    """A path that is a sibling of the project root is not managed."""
    sibling = tmp_path.parent / "other_project" / ".stackwinnow" / "envs" / "tool-a"
    sibling.mkdir(parents=True)
    _run(tmp_path, _STEP_A, owned_paths=[str(sibling)])

    plan = plan_removal(str(tmp_path))

    assert plan.items[0].action == RemovalAction.RETAIN


# ---------------------------------------------------------------------------
# 3. Shared path → RETAIN
# ---------------------------------------------------------------------------


def test_shared_path_is_retained_when_other_tool_in_scope(tmp_path):
    """A path referenced by a retained tool is kept even if the removing tool owns it too."""
    shared = tmp_path / ".stackwinnow" / "envs" / "shared" / "bin"
    shared.mkdir(parents=True)
    path_str = str(shared)

    # Seed both tools with the same owned path.
    execute_plan(
        _plan(tmp_path, [_STEP_A, _STEP_B]),
        step_runner=lambda s: RunnerOutcome(
            status=OperationStatus.SUCCEEDED,
            message="ok",
            owned_paths=[path_str],
        ),
    )

    # Remove only tool-a; tool-b still references the path.
    plan = plan_removal(str(tmp_path), tool_ids=["tool-a"])

    assert len(plan.items) == 1
    assert plan.items[0].action == RemovalAction.RETAIN
    assert "shared" in plan.items[0].reason.lower()


# ---------------------------------------------------------------------------
# 4. Exclusively managed path → REMOVE
# ---------------------------------------------------------------------------


def test_managed_exclusive_path_is_candidate(tmp_path):
    """An exclusively owned managed path is classified for removal."""
    managed = tmp_path / ".stackwinnow" / "envs" / "tool-a" / "python"
    managed.mkdir(parents=True)
    _run(tmp_path, _STEP_A, owned_paths=[str(managed)])

    plan = plan_removal(str(tmp_path))

    assert len(plan.candidates) == 1
    assert len(plan.retained) == 0
    assert plan.candidates[0].tool_id == "tool-a"
    assert plan.candidates[0].step_id == "tool-a-install"


def test_multiple_managed_paths_all_classified(tmp_path):
    """Each owned path in a receipt is classified independently."""
    envs = tmp_path / ".stackwinnow" / "envs" / "tool-a"
    python_env = envs / "python"
    node_env = envs / "node"
    python_env.mkdir(parents=True)
    node_env.mkdir(parents=True)

    _run(tmp_path, _STEP_A, owned_paths=[str(python_env), str(node_env)])

    plan = plan_removal(str(tmp_path))

    assert len(plan.candidates) == 2
    paths = {item.path for item in plan.candidates}
    assert str(python_env) in paths
    assert str(node_env) in paths


# ---------------------------------------------------------------------------
# 5. tool_ids scoping
# ---------------------------------------------------------------------------


def test_scoped_plan_excludes_other_tools(tmp_path):
    """When tool_ids is provided, only those tools contribute candidates."""
    path_a = tmp_path / ".stackwinnow" / "envs" / "tool-a" / "python"
    path_b = tmp_path / ".stackwinnow" / "envs" / "tool-b" / "python"
    path_a.mkdir(parents=True)
    path_b.mkdir(parents=True)

    execute_plan(
        _plan(tmp_path, [_STEP_A, _STEP_B]),
        step_runner=lambda s: RunnerOutcome(
            status=OperationStatus.SUCCEEDED,
            message="ok",
            owned_paths=[str(path_a) if s.tool_id == "tool-a" else str(path_b)],
        ),
    )

    plan = plan_removal(str(tmp_path), tool_ids=["tool-a"])

    assert len(plan.candidates) == 1
    assert plan.candidates[0].tool_id == "tool-a"
    # tool-b's path is not even in the plan items
    assert all(item.tool_id == "tool-a" for item in plan.items)


def test_plan_without_scope_includes_all_tools(tmp_path):
    """Passing tool_ids=None includes all tools with succeeded receipts."""
    path_a = tmp_path / ".stackwinnow" / "envs" / "tool-a" / "python"
    path_b = tmp_path / ".stackwinnow" / "envs" / "tool-b" / "python"
    path_a.mkdir(parents=True)
    path_b.mkdir(parents=True)

    execute_plan(
        _plan(tmp_path, [_STEP_A, _STEP_B]),
        step_runner=lambda s: RunnerOutcome(
            status=OperationStatus.SUCCEEDED,
            message="ok",
            owned_paths=[str(path_a) if s.tool_id == "tool-a" else str(path_b)],
        ),
    )

    plan = plan_removal(str(tmp_path))

    tool_ids = {item.tool_id for item in plan.candidates}
    assert tool_ids == {"tool-a", "tool-b"}


# ---------------------------------------------------------------------------
# 6. Failed receipts are excluded
# ---------------------------------------------------------------------------


def test_failed_receipt_paths_not_in_plan(tmp_path):
    """Paths from failed or blocked steps never become removal candidates."""
    managed = tmp_path / ".stackwinnow" / "envs" / "tool-a" / "python"
    managed.mkdir(parents=True)
    _run_failed(tmp_path, _STEP_A, owned_paths=[str(managed)])

    plan = plan_removal(str(tmp_path))

    assert plan.items == []


def test_step_without_owned_paths_adds_no_items(tmp_path):
    """A succeeded step that recorded no owned_paths contributes nothing."""
    _run(tmp_path, _STEP_A, owned_paths=[])

    plan = plan_removal(str(tmp_path))

    assert plan.items == []


# ---------------------------------------------------------------------------
# 7. Empty / no-receipt case
# ---------------------------------------------------------------------------


def test_no_receipts_produces_empty_plan(tmp_path):
    """A project with no execution record returns an empty plan."""
    plan = plan_removal(str(tmp_path))

    assert isinstance(plan, RemovalPlan)
    assert plan.items == []
    assert plan.candidates == []
    assert plan.retained == []


# ---------------------------------------------------------------------------
# 8. Receipts file protection
# ---------------------------------------------------------------------------


def test_receipts_file_is_protected(tmp_path):
    """If a step mistakenly claims the receipts file, it is always retained."""
    # Seed a succeeded receipt first so the file exists.
    _run(tmp_path, _STEP_A, owned_paths=[])

    receipts_path = str(tmp_path / ".stackwinnow" / "receipts.json")

    # Manually run a second plan that claims the receipts file as owned.
    execute_plan(
        _plan(tmp_path, [_STEP_B]),
        step_runner=lambda s: RunnerOutcome(
            status=OperationStatus.SUCCEEDED,
            message="ok",
            owned_paths=[receipts_path],
        ),
    )

    plan = plan_removal(str(tmp_path), tool_ids=["tool-b"])

    assert len(plan.items) == 1
    assert plan.items[0].action == RemovalAction.RETAIN
    assert "receipts" in plan.items[0].reason.lower()

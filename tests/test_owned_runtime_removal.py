"""Acceptance tests for managed-resource removal planning (B02 corrections).

Verifies the full classification rule set:
  1. Absent paths → RETAIN (nothing to delete).
  2. External paths (outside .stackwinnow/) → RETAIN.
  3. Symlinks → RETAIN (unsafe alias).
  4. Shared infrastructure (.stackwinnow dir, receipts, lock) → RETAIN.
  5. Project data (results, graphs, reports, caches) → RETAIN.
  6. Paths shared with a retained tool → RETAIN (normalised comparison).
  7. Directories containing retained files → RETAIN (containment).
  8. Paths from failed/interrupted steps → RETAIN.
  9. Exclusively managed paths → REMOVE.
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


# ---------------------------------------------------------------------------
# B02 — new classification rules
# ---------------------------------------------------------------------------


def test_symlink_inside_managed_prefix_is_retained(tmp_path):
    """A symlink inside .stackwinnow/ must not be removed automatically."""
    target = tmp_path / "external_target"
    target.mkdir()
    link = tmp_path / ".stackwinnow" / "envs" / "tool-a" / "python"
    link.parent.mkdir(parents=True)
    link.symlink_to(target)

    _run(tmp_path, _STEP_A, owned_paths=[str(link)])
    plan = plan_removal(str(tmp_path))

    assert len(plan.items) == 1
    assert plan.items[0].action == RemovalAction.RETAIN
    assert "symlink" in plan.items[0].reason.lower()


def test_operation_lock_file_is_retained(tmp_path):
    """The operation lock file is shared infrastructure and must never be removed."""
    lock_path = tmp_path / ".stackwinnow" / "operation.lock"

    # Seed a succeeded receipt that claims the lock file as owned.
    _run(tmp_path, _STEP_A, owned_paths=[str(lock_path)])
    # Recreate the file so plan_removal sees an existing path to classify.
    lock_path.touch()

    plan = plan_removal(str(tmp_path))

    assert len(plan.items) == 1
    assert plan.items[0].action == RemovalAction.RETAIN
    assert "infrastructure" in plan.items[0].reason.lower()


def test_managed_prefix_itself_is_retained(tmp_path):
    """The .stackwinnow/ directory itself is infrastructure and must not be a candidate."""
    managed = tmp_path / ".stackwinnow"

    # Seed receipt claiming .stackwinnow/ itself, then ensure it exists for classification.
    _run(tmp_path, _STEP_A, owned_paths=[str(managed)])
    managed.mkdir(parents=True, exist_ok=True)

    plan = plan_removal(str(tmp_path))

    assert len(plan.items) == 1
    assert plan.items[0].action == RemovalAction.RETAIN
    assert "infrastructure" in plan.items[0].reason.lower()


def test_results_directory_is_retained_as_project_data(tmp_path):
    """A results/ sub-directory inside .stackwinnow/ is project data, not removable."""
    results = tmp_path / ".stackwinnow" / "promptfoo" / "results"
    results.mkdir(parents=True)

    _run(tmp_path, _STEP_A, owned_paths=[str(results)])
    plan = plan_removal(str(tmp_path))

    assert len(plan.items) == 1
    assert plan.items[0].action == RemovalAction.RETAIN
    assert "project data" in plan.items[0].reason.lower()


def test_graphs_directory_is_retained_as_project_data(tmp_path):
    """A graphs/ sub-directory inside .stackwinnow/ is project data, not removable."""
    graphs = tmp_path / ".stackwinnow" / "graphify" / "graphs"
    graphs.mkdir(parents=True)

    _run(tmp_path, _STEP_A, owned_paths=[str(graphs)])
    plan = plan_removal(str(tmp_path))

    assert plan.items[0].action == RemovalAction.RETAIN
    assert "project data" in plan.items[0].reason.lower()


def test_failed_step_path_is_retained_even_when_in_scope(tmp_path):
    """Paths from failed steps are always protected, even when the tool is in scope."""
    managed = tmp_path / ".stackwinnow" / "envs" / "tool-a" / "python"
    managed.mkdir(parents=True)
    _run_failed(tmp_path, _STEP_A, owned_paths=[str(managed)])

    # A second plan marks the step as FAILED so plan_removal sees it as partial state.
    plan = plan_removal(str(tmp_path), tool_ids=["tool-a"])

    # The path exists and is in scope, but came from a failed step — retain it.
    assert plan.items == [] or all(i.action == RemovalAction.RETAIN for i in plan.items)


def test_relative_and_absolute_paths_to_same_resource_treated_as_shared(tmp_path):
    """Absolute path in one receipt and relative path in another resolve to the same
    resource; the shared-use check must protect it."""
    shared = tmp_path / ".stackwinnow" / "envs" / "shared" / "bin"
    shared.mkdir(parents=True)

    abs_path = str(shared)
    rel_path = str(shared.relative_to(tmp_path))

    # tool-a records the absolute path; tool-b records the relative path.
    execute_plan(
        _plan(tmp_path, [_STEP_A, _STEP_B]),
        step_runner=lambda s: RunnerOutcome(
            status=OperationStatus.SUCCEEDED,
            message="ok",
            owned_paths=[abs_path if s.tool_id == "tool-a" else rel_path],
        ),
    )

    # Remove only tool-a; tool-b's relative path should protect the shared resource.
    plan = plan_removal(str(tmp_path), tool_ids=["tool-a"])

    assert len(plan.items) == 1
    assert plan.items[0].action == RemovalAction.RETAIN
    assert "shared" in plan.items[0].reason.lower()


def test_directory_containing_retained_file_is_itself_retained(tmp_path):
    """A parent directory owned by tool-a is retained when tool-b owns a file inside it."""
    parent = tmp_path / ".stackwinnow" / "envs" / "shared"
    child = parent / "data.json"
    parent.mkdir(parents=True)
    child.write_text("{}")

    # tool-a owns the parent directory; tool-b owns the file inside it.
    execute_plan(
        _plan(tmp_path, [_STEP_A, _STEP_B]),
        step_runner=lambda s: RunnerOutcome(
            status=OperationStatus.SUCCEEDED,
            message="ok",
            owned_paths=[str(parent) if s.tool_id == "tool-a" else str(child)],
        ),
    )

    # Remove tool-a; its parent dir contains tool-b's file, so it must be retained.
    plan = plan_removal(str(tmp_path), tool_ids=["tool-a"])

    assert len(plan.items) == 1
    assert plan.items[0].action == RemovalAction.RETAIN
    assert "contains" in plan.items[0].reason.lower()


# ---------------------------------------------------------------------------
# B02 — new regression tests for PR #21 review findings
# ---------------------------------------------------------------------------


def test_graphify_state_path_retained_when_graph_evidence_inside(tmp_path):
    """STATE_PATH owned by graphify is RETAIN when graph.json evidence is inside it.

    P1: Preserve actual project-data paths and their removable ancestors.
    """
    from stackwinnow.adapters.graphify import GRAPH_PATH, STATE_PATH
    from stackwinnow.contracts import EvidenceRef

    graph = tmp_path / GRAPH_PATH
    graph.parent.mkdir(parents=True)
    graph.write_text('{"nodes": [], "edges": []}')
    state_abs = str(tmp_path / STATE_PATH)

    execute_plan(
        _plan(tmp_path, [_STEP_A]),
        step_runner=lambda s: RunnerOutcome(
            status=OperationStatus.SUCCEEDED,
            message="ok",
            owned_paths=[state_abs],
            evidence=[EvidenceRef(source=GRAPH_PATH, detail="sha256:abc")],
        ),
    )

    plan = plan_removal(str(tmp_path))

    assert len(plan.items) == 1
    assert plan.items[0].action == RemovalAction.RETAIN


def test_parent_retained_when_owned_child_is_project_data(tmp_path):
    """When a receipt owns both parent and a results/ child, the parent is also retained.

    P1: Internally contradictory plan — parent REMOVE while child results RETAIN.
    """
    parent = tmp_path / ".stackwinnow" / "promptfoo"
    child = parent / "results"
    parent.mkdir(parents=True)
    child.mkdir()

    execute_plan(
        _plan(tmp_path, [_STEP_A]),
        step_runner=lambda s: RunnerOutcome(
            status=OperationStatus.SUCCEEDED,
            message="ok",
            owned_paths=[str(parent), str(child)],
        ),
    )

    plan = plan_removal(str(tmp_path))

    assert all(item.action == RemovalAction.RETAIN for item in plan.items), (
        "Both parent and results/ child should be RETAIN; got: "
        + str([(i.path, i.action, i.reason) for i in plan.items])
    )


def test_child_inside_retained_parent_is_retained(tmp_path):
    """A file owned by tool-a inside a directory retained by tool-b must be retained.

    P1: Inverse containment — descendant inside a retained owned directory.
    """
    parent = tmp_path / ".stackwinnow" / "envs" / "shared"
    child = parent / "bin" / "python"
    child.parent.mkdir(parents=True)
    child.touch()

    execute_plan(
        _plan(tmp_path, [_STEP_A, _STEP_B]),
        step_runner=lambda s: RunnerOutcome(
            status=OperationStatus.SUCCEEDED,
            message="ok",
            owned_paths=[str(child) if s.tool_id == "tool-a" else str(parent)],
        ),
    )

    plan = plan_removal(str(tmp_path), tool_ids=["tool-a"])

    assert len(plan.items) == 1
    assert plan.items[0].action == RemovalAction.RETAIN


def test_path_through_symlinked_ancestor_is_retained(tmp_path):
    """A regular leaf file reached via a symlinked parent is retained.

    P2: Reject symlink ancestors before accepting a managed candidate.
    """
    target = tmp_path / ".stackwinnow" / "envs" / "shared"
    target.mkdir(parents=True)
    link = tmp_path / "external-alias"
    link.symlink_to(target)

    (target / "bin").mkdir()
    (target / "bin" / "python").touch()
    leaf = link / "bin" / "python"

    _run(tmp_path, _STEP_A, owned_paths=[str(leaf)])

    plan = plan_removal(str(tmp_path))

    assert len(plan.items) == 1
    assert plan.items[0].action == RemovalAction.RETAIN


"""Failing tests for B04 — Graphify managed indexing and relationship verification.

Written before the implementation so the CI check is red first.
Once graphify_index.py exists and graphify_plan.py drops the index blocker,
all tests should pass.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from stackwinnow.adapters import graphify_install as install_adapter
from stackwinnow.adapters import graphify_plan as preparation
from stackwinnow.adapters.graphify import (
    GRAPH_PATH,
    INDEX_PATH,
    STATE_PATH,
    GraphifyError,
    RelationshipExpectation,
    check_relationship,
)
from stackwinnow.adapters.graphify_plan import GraphifyExecutionPlan
from stackwinnow.contracts import OperationStatus
from stackwinnow.installer import ExecutionRecord, RunnerOutcome, StepReceipt
from stackwinnow.runner import CommandResult

# ---------------------------------------------------------------------------
# Fixtures shared with the install adapter tests
# ---------------------------------------------------------------------------

_RUNTIME = None


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project with spaces"
    root.mkdir()
    (root / "caller.py").write_text("from callee import answer\ndef call(): return answer()\n")
    (root / "callee.py").write_text("def answer(): return 42\n")
    runtime = preparation.RuntimeSnapshot(
        executable=sys.executable,
        implementation="CPython",
        version="3.11.14",
        system="Darwin",
        machine="arm64",
        macos_version="14.0",
    )
    monkeypatch.setattr(preparation, "_runtime", lambda: runtime)
    return root


@pytest.fixture
def plan(project):
    return preparation.plan_graphify_execution(
        project,
        expectation=RelationshipExpectation(
            caller_file="caller.py",
            caller_label="call()",
            callee_file="callee.py",
            callee_label="answer()",
        ),
    )


EXPECTATION = RelationshipExpectation(
    caller_file="caller.py",
    caller_label="call()",
    callee_file="callee.py",
    callee_label="answer()",
)


def _seed_install(root: Path) -> None:
    """Write a succeeded install receipt so the index adapter's prereq check passes."""
    from stackwinnow.adapters.graphify_install import INSTALL_ROOT, STEP_ID
    from stackwinnow.contracts import EvidenceRef
    from stackwinnow.installer import ExecutionRecord, StepReceipt

    managed = root / ".stackwinnow"
    managed.mkdir(exist_ok=True)

    record_path = managed / "receipts.json"
    record = ExecutionRecord(project_root=str(root))
    record.steps.append(
        StepReceipt(
            step_id=STEP_ID,
            tool_id="graphify",
            status="succeeded",
            message="fake install",
            owned_paths=[INSTALL_ROOT],
            evidence=[EvidenceRef(source=f"{INSTALL_ROOT}/installation.json", detail="sha256:abc")],
            timestamp="2026-01-01T00:00:00",
        )
    )
    record_path.write_text(record.model_dump_json())


def _fake_graph(root: Path, expectation: RelationshipExpectation) -> bytes:
    """Create a valid graph.json at GRAPH_PATH and return its bytes."""
    graph = {
        "nodes": [
            {
                "id": "caller",
                "source_file": expectation.caller_file,
                "label": expectation.caller_label,
            },
            {
                "id": "callee",
                "source_file": expectation.callee_file,
                "label": expectation.callee_label,
            },
        ],
        "edges": [
            {
                "source": "caller",
                "target": "callee",
                "relation": "calls",
                "confidence": "EXTRACTED",
            }
        ],
    }
    graph_path = root / GRAPH_PATH
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(graph, sort_keys=True).encode()
    graph_path.write_bytes(raw)
    return raw


class FakeIndex:
    """Minimal fake command runner for indexing tests."""

    def __init__(self, *, fail=False, graph_factory=None):
        self.calls = []
        self.fail = fail
        self.graph_factory = graph_factory

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.fail:
            return CommandResult(1, "", "controlled failure")
        root = Path(kwargs["cwd"])
        if self.graph_factory:
            self.graph_factory(root)
        return CommandResult(0, "indexed ok", "")


# ---------------------------------------------------------------------------
# 1. Module constants
# ---------------------------------------------------------------------------


def test_index_step_id_is_graphify_index_code():
    """INDEX_STEP_ID must match the 'index-code' operation declared in the execution plan."""
    from stackwinnow.adapters.graphify_index import INDEX_STEP_ID

    assert INDEX_STEP_ID == "graphify-index-code"


# ---------------------------------------------------------------------------
# 2. Prerequisite guard — install receipt must exist
# ---------------------------------------------------------------------------


def test_index_raises_without_install_receipt(project, plan):
    """apply_graphify_index must raise when no install receipt exists."""
    from stackwinnow.adapters.graphify_index import apply_graphify_index

    with pytest.raises(GraphifyError, match="install"):
        apply_graphify_index(plan)


# ---------------------------------------------------------------------------
# 3. Dry run
# ---------------------------------------------------------------------------


def test_dry_run_has_no_commands_or_files(project, plan, monkeypatch):
    """Dry run must not execute any commands or create any files."""
    from stackwinnow.adapters.graphify_index import apply_graphify_index

    _seed_install(project)

    def forbidden(*args, **kwargs):
        raise AssertionError("dry run must not execute commands")

    monkeypatch.setattr("subprocess.Popen", forbidden)
    before = {str(p): p.read_bytes() for p in project.rglob("*") if p.is_file()}

    result = apply_graphify_index(plan, dry_run=True)

    assert result.dry_run
    assert not (project / STATE_PATH).exists()
    assert {str(p): p.read_bytes() for p in project.rglob("*") if p.is_file()} == before


# ---------------------------------------------------------------------------
# 4. Successful index + relationship check
# ---------------------------------------------------------------------------


def test_successful_index_records_state_path_as_owned(project, plan):
    """A succeeded index step must own STATE_PATH."""
    from stackwinnow.adapters.graphify_index import INDEX_STEP_ID, apply_graphify_index

    _seed_install(project)
    runner = FakeIndex(graph_factory=lambda root: _fake_graph(root, EXPECTATION))

    result = apply_graphify_index(plan, command_runner=runner)

    assert result.indexed
    receipt = result.record.receipt_for(INDEX_STEP_ID)
    assert receipt is not None
    assert STATE_PATH in receipt.owned_paths or any(
        STATE_PATH in p for p in receipt.owned_paths
    )


def test_successful_index_records_graph_evidence(project, plan):
    """Evidence must include the graph.json sha256."""
    from stackwinnow.adapters.graphify_index import INDEX_STEP_ID, apply_graphify_index

    _seed_install(project)
    runner = FakeIndex(graph_factory=lambda root: _fake_graph(root, EXPECTATION))

    result = apply_graphify_index(plan, command_runner=runner)

    receipt = result.record.receipt_for(INDEX_STEP_ID)
    assert receipt is not None and receipt.evidence
    assert any(GRAPH_PATH in ev.source for ev in receipt.evidence)
    assert any("sha256:" in ev.detail for ev in receipt.evidence)


def test_successful_index_relationship_check_succeeded(project, plan):
    """When the graph contains the expected relationship, check status must be succeeded."""
    from stackwinnow.adapters.graphify_index import apply_graphify_index

    _seed_install(project)
    runner = FakeIndex(graph_factory=lambda root: _fake_graph(root, EXPECTATION))

    result = apply_graphify_index(plan, command_runner=runner)

    assert result.relationship_check is not None
    assert result.relationship_check.status == OperationStatus.SUCCEEDED


# ---------------------------------------------------------------------------
# 5. Failure handling
# ---------------------------------------------------------------------------


def test_failed_command_produces_failed_result(project, plan):
    """When the index command exits non-zero, the result must be failed."""
    from stackwinnow.adapters.graphify_index import apply_graphify_index

    _seed_install(project)
    runner = FakeIndex(fail=True)

    result = apply_graphify_index(plan, command_runner=runner)

    assert not result.indexed
    assert result.results and result.results[0].status == OperationStatus.FAILED


def test_blocked_if_state_path_exists_unowned(project, plan):
    """If STATE_PATH exists but has no ownership receipt, raise before running commands."""
    from stackwinnow.adapters.graphify_index import apply_graphify_index

    _seed_install(project)
    (project / STATE_PATH).mkdir(parents=True)
    runner = FakeIndex()

    with pytest.raises(GraphifyError):
        apply_graphify_index(plan, command_runner=runner)

    assert not runner.calls


# ---------------------------------------------------------------------------
# 6. graphify_plan no longer has the index pending blocker
# ---------------------------------------------------------------------------


def test_graphify_plan_does_not_include_index_pending_blocker(plan):
    """After B04, the execution plan must not list indexing as pending."""
    for blocker in plan.blockers:
        assert "index" not in blocker.lower() or "pending" not in blocker.lower(), (
            f"Unexpected index blocker: {blocker!r}"
        )

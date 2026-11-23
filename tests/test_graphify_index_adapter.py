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

from stackwinnow.adapters import graphify_plan as preparation
from stackwinnow.adapters.graphify import (
    GRAPH_PATH,
    STATE_PATH,
    GraphifyError,
    RelationshipExpectation,
)
from stackwinnow.contracts import OperationStatus
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
    """Run the installer with a controlled runtime, including real ownership evidence."""
    from stackwinnow.adapters.graphify_install import apply_graphify_install

    def runner(argv, **kwargs):
        if "venv" in argv:
            python = root / preparation.ENV_PATH / "bin/python"
            python.parent.mkdir(parents=True)
            python.write_text("fixture interpreter")
        return CommandResult(0, "verified", "")

    candidate = preparation.plan_graphify_execution(root, expectation=EXPECTATION)
    assert apply_graphify_install(candidate, command_runner=runner).installed


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
        if "extract" in argv and self.graph_factory:
            source = Path(argv[argv.index("extract") + 1])
            self.graph_factory(source)
            output = Path(argv[argv.index("--out") + 1]) / "graphify-out/graph.json"
            output.parent.mkdir(parents=True)
            output.write_bytes((source / GRAPH_PATH).read_bytes())
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
    assert STATE_PATH in receipt.owned_paths or any(STATE_PATH in p for p in receipt.owned_paths)


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


@pytest.fixture
def index_plan(project):
    from stackwinnow.adapters.graphify_index import plan_graphify_index

    _seed_install(project)
    return plan_graphify_index(project, expectation=EXPECTATION)


def _good_runner():
    return FakeIndex(graph_factory=lambda root: _fake_graph(root, EXPECTATION))


def test_reviewed_plan_repeat_reuses_only_current_evidence(project, index_plan):
    from stackwinnow.adapters.graphify_index import apply_graphify_index

    runner = _good_runner()
    first = apply_graphify_index(index_plan, command_runner=runner)
    assert first.indexed and len(runner.calls) == 2
    before = (project / ".stackwinnow/receipts.json").read_bytes()
    again = apply_graphify_index(index_plan, command_runner=runner)
    assert again.indexed and again.results[0].status == "skipped"
    assert len(runner.calls) == 2
    assert (project / ".stackwinnow/receipts.json").read_bytes() == before


@pytest.mark.parametrize(
    "change", ["source", "additional-source", "deleted-graph", "changed-graph", "runtime"]
)
def test_current_state_is_required_before_reuse(project, index_plan, change):
    from stackwinnow.adapters.graphify_index import apply_graphify_index

    runner = _good_runner()
    assert apply_graphify_index(index_plan, command_runner=runner).indexed
    if change == "source":
        (project / "callee.py").write_text("def answer(): return 7\n")
    elif change == "additional-source":
        (project / "other.py").write_text("def other(): return 1\n")
    elif change == "deleted-graph":
        (project / GRAPH_PATH).unlink()
    elif change == "changed-graph":
        (project / GRAPH_PATH).write_text("{}")
    else:
        (project / preparation.ENV_PATH / "bin/python").write_text("modified runtime")
    before = (project / ".stackwinnow/receipts.json").read_bytes()
    with pytest.raises(GraphifyError):
        apply_graphify_index(index_plan, command_runner=runner)
    assert len(runner.calls) == 2
    assert (project / ".stackwinnow/receipts.json").read_bytes() == before


@pytest.mark.parametrize(
    "change", ["source", "additional-source", "deleted-graph", "changed-graph"]
)
def test_deliberate_replan_stages_new_graph(project, index_plan, change):
    from stackwinnow.adapters.graphify_index import (
        apply_graphify_index,
        inspect_graphify_index,
        plan_graphify_index,
    )

    runner = _good_runner()
    assert apply_graphify_index(index_plan, command_runner=runner).indexed
    if change == "source":
        (project / "callee.py").write_text("def answer(): return 7\n")
    elif change == "additional-source":
        (project / "other.py").write_text("def other(): return 1\n")
    elif change == "deleted-graph":
        (project / GRAPH_PATH).unlink()
    else:
        (project / GRAPH_PATH).write_text("{}")
    revised = plan_graphify_index(project, expectation=EXPECTATION)
    assert revised != index_plan
    assert apply_graphify_index(revised, command_runner=runner).indexed
    assert len(runner.calls) == 4
    proof, relationship = inspect_graphify_index(project)
    assert proof.plan == revised and relationship.status == "succeeded"


@pytest.mark.parametrize(
    "failure", ["runner-raises", "malformed-json", "query-fails", "source-races", "publication"]
)
def test_failed_index_preserves_durable_ownership(project, index_plan, failure, monkeypatch):
    from stackwinnow.adapters import graphify_index as adapter

    runner = _good_runner()

    def command(argv, **kwargs):
        if failure == "runner-raises":
            raise OSError("simulated command launch failure")
        result = runner(argv, **kwargs)
        if "extract" in argv:
            if failure == "malformed-json":
                (Path(argv[argv.index("--out") + 1]) / "graphify-out/graph.json").write_text("{")
            if failure == "source-races":
                (project / "callee.py").write_text("def answer(): return 0\n")
        elif failure == "query-fails":
            return CommandResult(4, "", "missing symbol")
        return result

    if failure == "publication":

        def publish(*args):
            raise OSError("simulated publication failure")

        monkeypatch.setattr(adapter, "_publish", publish)
    result = adapter.apply_graphify_index(index_plan, command_runner=command)
    assert not result.indexed
    receipt = result.record.receipt_for(adapter.INDEX_STEP_ID)
    assert receipt.status == "failed" and receipt.owned_paths == [STATE_PATH]
    assert (project / STATE_PATH).is_dir()
    from stackwinnow.adapters._managed import record_for

    assert record_for(project).receipt_for(adapter.INDEX_STEP_ID) == receipt
    with pytest.raises(GraphifyError, match="inspection"):
        adapter.plan_graphify_index(project, expectation=EXPECTATION)


@pytest.mark.parametrize("change", ["install-receipt", "index-receipt", "provenance", "symlink"])
def test_untrusted_ownership_never_allows_commands(project, index_plan, change, tmp_path):
    from stackwinnow.adapters.graphify_index import PROVENANCE_PATH, apply_graphify_index

    runner = _good_runner()
    assert apply_graphify_index(index_plan, command_runner=runner).indexed
    receipt_path = project / ".stackwinnow/receipts.json"
    value = json.loads(receipt_path.read_text())
    if change == "install-receipt":
        value["steps"][0]["evidence"] = []
        receipt_path.write_text(json.dumps(value))
    elif change == "index-receipt":
        value["steps"][1]["tool_id"] = "promptfoo"
        receipt_path.write_text(json.dumps(value))
    elif change == "provenance":
        (project / PROVENANCE_PATH).write_text("{}")
    else:
        original = project / STATE_PATH
        original.rename(tmp_path / "external-state")
        original.symlink_to(tmp_path / "external-state", target_is_directory=True)
    with pytest.raises(GraphifyError):
        apply_graphify_index(index_plan, command_runner=runner)
    assert len(runner.calls) == 2


def test_install_reapply_after_index_keeps_runtime_and_graph(project, plan):
    from stackwinnow.adapters.graphify_index import apply_graphify_index, plan_graphify_index
    from stackwinnow.adapters.graphify_install import apply_graphify_install

    _seed_install(project)
    candidate = plan_graphify_index(project, expectation=EXPECTATION)
    assert apply_graphify_index(candidate, command_runner=_good_runner()).indexed

    def forbidden(*args, **kwargs):
        raise AssertionError("intact installation must be reused")

    result = apply_graphify_install(plan, command_runner=forbidden)
    assert result.installed and result.results[0].status == "skipped"
    assert (project / GRAPH_PATH).is_file()


def test_snapshot_rejects_aliases_and_reviews_all_included_files(project, index_plan, tmp_path):
    from stackwinnow.adapters.graphify_index import plan_graphify_index

    external = tmp_path / "foreign.py"
    external.write_text("print(42)")
    (project / "alias.py").symlink_to(external)
    with pytest.raises(GraphifyError, match="regular files"):
        plan_graphify_index(project, expectation=EXPECTATION)


def test_index_validation_runs_under_shared_lock(project, index_plan, monkeypatch):
    from stackwinnow.adapters import graphify_index as adapter
    from stackwinnow.state.lock import ProjectLockError, project_lock

    original = adapter._validate

    def validate(candidate):
        with pytest.raises(ProjectLockError):
            with project_lock(str(project)):
                pass
        return original(candidate)

    monkeypatch.setattr(adapter, "_validate", validate)
    assert adapter.apply_graphify_index(index_plan, command_runner=_good_runner()).indexed


def test_shared_verifier_reads_current_evidence_and_runs_fresh_query(project, index_plan):
    from stackwinnow.adapters.graphify_index import apply_graphify_index
    from stackwinnow.verify import check_project

    runner = _good_runner()
    assert apply_graphify_index(index_plan, command_runner=runner).indexed
    before = (project / ".stackwinnow/receipts.json").read_bytes()
    report = check_project(project, tool_ids=["graphify"], command_runner=runner)
    checks = {check.kind: check for check in report.tools[0].checks}
    assert checks["installed"].status == "succeeded"
    assert checks["configured"].status == "blocked"
    assert checks["functional"].status == "not_run" and checks["connected"].status == "blocked"
    assert not report.ready and len(runner.calls) == 2
    assert (project / ".stackwinnow/receipts.json").read_bytes() == before
    functional = check_project(
        project, tool_ids=["graphify"], run_functional=True, command_runner=runner
    )
    assert (
        next(c for c in functional.tools[0].checks if c.kind == "functional").status == "succeeded"
    )
    assert not functional.ready and len(runner.calls) == 3
    (project / "callee.py").write_text("def answer(): return 3\n")
    stale = check_project(
        project, tool_ids=["graphify"], run_functional=True, command_runner=runner
    )
    assert next(c for c in stale.tools[0].checks if c.kind == "functional").status == "blocked"
    assert len(runner.calls) == 3


def test_shared_verifier_failed_query_cannot_reuse_old_success(project, index_plan):
    from stackwinnow.adapters.graphify_index import apply_graphify_index
    from stackwinnow.verify import check_project

    assert apply_graphify_index(index_plan, command_runner=_good_runner()).indexed
    good = check_project(
        project, tool_ids=["graphify"], run_functional=True, command_runner=_good_runner()
    )
    assert next(c for c in good.tools[0].checks if c.kind == "functional").status == "succeeded"
    failed = check_project(
        project, tool_ids=["graphify"], run_functional=True, command_runner=FakeIndex(fail=True)
    )
    assert next(c for c in failed.tools[0].checks if c.kind == "functional").status == "failed"


def test_index_cli_plan_dry_run_and_stale_error(project, index_plan, tmp_path, capsys):
    from stackwinnow.cli import main

    expected = tmp_path / "expected.json"
    expected.write_text(EXPECTATION.model_dump_json())
    assert (
        main(["graphify", "index-plan", str(project), "--expectation", str(expected), "--json"])
        == 0
    )
    plan_file = tmp_path / "index-plan.json"
    plan_file.write_text(capsys.readouterr().out)
    assert main(["graphify", "index", str(plan_file), "--dry-run", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"]
    (project / "callee.py").write_text("changed")
    with pytest.raises(SystemExit) as error:
        main(["graphify", "index", str(plan_file)])
    assert error.value.code == 2


def test_install_reapply_after_changed_source_reindex(project, plan):
    from stackwinnow.adapters.graphify_index import apply_graphify_index, plan_graphify_index
    from stackwinnow.adapters.graphify_install import apply_graphify_install

    _seed_install(project)
    original = plan_graphify_index(project, expectation=EXPECTATION)
    assert apply_graphify_index(original, command_runner=_good_runner()).indexed
    (project / "callee.py").write_text("def answer(): return 123\n")
    revised = plan_graphify_index(project, expectation=EXPECTATION)
    assert apply_graphify_index(revised, command_runner=_good_runner()).indexed

    def forbidden(*args, **kwargs):
        raise AssertionError("intact installation must be reused after source changes")

    assert apply_graphify_install(plan, command_runner=forbidden).installed


def test_legacy_manifest_requires_original_plan_and_preserves_runtime(project, plan):
    from stackwinnow.adapters.graphify_index import apply_graphify_index, plan_graphify_index
    from stackwinnow.adapters.graphify_install import MANIFEST, apply_graphify_install
    from stackwinnow.verify import check_project

    _seed_install(project)
    # Reproduce the previously released schema rather than inventing ownership.
    manifest_file = project / MANIFEST
    manifest = json.loads(manifest_file.read_text())
    manifest.pop("plan")
    manifest["schema_version"] = 1
    raw = json.dumps(manifest).encode()
    manifest_file.write_bytes(raw)
    receipt_file = project / ".stackwinnow/receipts.json"
    record = json.loads(receipt_file.read_text())
    record["steps"][0]["evidence"][0]["detail"] = "sha256:" + preparation._digest(raw)
    receipt_file.write_text(json.dumps(record))
    with pytest.raises(GraphifyError, match="--installation-plan"):
        plan_graphify_index(project, expectation=EXPECTATION)
    candidate = plan_graphify_index(project, expectation=EXPECTATION, installation_plan=plan)
    assert apply_graphify_index(candidate, command_runner=_good_runner()).indexed
    assert apply_graphify_install(plan, command_runner=_good_runner()).installed
    report = check_project(
        project, tool_ids=["graphify"], run_functional=True, command_runner=_good_runner()
    )
    assert next(c for c in report.tools[0].checks if c.kind == "functional").status == "succeeded"
    assert manifest_file.read_bytes() == raw

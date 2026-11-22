"""Failing tests for B05 — Graphify Codex configuration integration.

Written before implementation; all must fail initially.
Once graphify_configure.py exists and graphify_plan.py drops the Codex
config blocker, all tests must pass.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

from stackwinnow.adapters import graphify_plan as preparation
from stackwinnow.adapters.graphify import (
    GRAPH_PATH,
    STATE_PATH,
    GraphifyError,
    RelationshipExpectation,
)
from stackwinnow.adapters.graphify_index import INDEX_STEP_ID
from stackwinnow.adapters.graphify_install import STEP_ID as INSTALL_STEP_ID
from stackwinnow.configure.codex import GRAPHIFY_SERVER
from stackwinnow.contracts import EvidenceRef, OperationStatus
from stackwinnow.installer import ExecutionRecord, StepReceipt

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "graphify-project"
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


def _seed_install(root: Path) -> None:
    from stackwinnow.adapters.graphify_install import INSTALL_ROOT, STEP_ID

    managed = root / ".stackwinnow"
    managed.mkdir(exist_ok=True)
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
    (managed / "receipts.json").write_text(record.model_dump_json())


def _seed_index(root: Path) -> None:
    managed = root / ".stackwinnow"
    managed.mkdir(exist_ok=True)
    record = ExecutionRecord.model_validate_json((managed / "receipts.json").read_text())
    record.steps.append(
        StepReceipt(
            step_id=INDEX_STEP_ID,
            tool_id="graphify",
            status="succeeded",
            message="fake index",
            owned_paths=[STATE_PATH],
            evidence=[EvidenceRef(source=GRAPH_PATH, detail="sha256:def")],
            timestamp="2026-01-01T00:00:01",
        )
    )
    (managed / "receipts.json").write_text(record.model_dump_json())


def _seed_install_and_index(root: Path) -> None:
    _seed_install(root)
    _seed_index(root)


# ---------------------------------------------------------------------------
# 1. Module constant
# ---------------------------------------------------------------------------


def test_configure_step_id_is_graphify_configure():
    """CONFIGURE_STEP_ID must match the 'configure' step name pattern."""
    from stackwinnow.adapters.graphify_configure import CONFIGURE_STEP_ID

    assert CONFIGURE_STEP_ID == "graphify-configure"


# ---------------------------------------------------------------------------
# 2. Prerequisite guard
# ---------------------------------------------------------------------------


def test_configure_raises_without_any_receipts(project, plan):
    """apply_graphify_configure must raise when no install or index receipts exist."""
    from stackwinnow.adapters.graphify_configure import apply_graphify_configure

    with pytest.raises(GraphifyError, match="install|index"):
        apply_graphify_configure(plan)


def test_configure_raises_without_index_receipt(project, plan):
    """apply_graphify_configure must raise when install succeeded but index has not run."""
    from stackwinnow.adapters.graphify_configure import apply_graphify_configure

    _seed_install(project)

    with pytest.raises(GraphifyError, match="index"):
        apply_graphify_configure(plan)


# ---------------------------------------------------------------------------
# 3. Dry run
# ---------------------------------------------------------------------------


def test_dry_run_no_writes(project, plan, monkeypatch):
    """Dry run must not write any files."""
    from stackwinnow.adapters.graphify_configure import apply_graphify_configure

    _seed_install_and_index(project)
    (project / ".codex").mkdir()

    before = {str(p): p.read_bytes() for p in project.rglob("*") if p.is_file()}

    result = apply_graphify_configure(plan, dry_run=True)

    assert result.dry_run
    assert {str(p): p.read_bytes() for p in project.rglob("*") if p.is_file()} == before


# ---------------------------------------------------------------------------
# 4. Successful configure
# ---------------------------------------------------------------------------


def test_configure_creates_codex_config_entry(project, plan):
    """apply_graphify_configure must write the Graphify server entry in .codex/config.toml."""
    from stackwinnow.adapters.graphify_configure import apply_graphify_configure

    _seed_install_and_index(project)
    (project / ".codex").mkdir()

    result = apply_graphify_configure(plan)

    assert result.configured
    toml = tomllib.loads((project / ".codex/config.toml").read_text())
    assert GRAPHIFY_SERVER in toml.get("mcp_servers", {})


def test_configure_records_configuration_ownership(project, plan):
    """The configure receipt must carry configuration_ownership with the Graphify patch."""
    from stackwinnow.adapters.graphify_configure import CONFIGURE_STEP_ID, apply_graphify_configure

    _seed_install_and_index(project)
    (project / ".codex").mkdir()

    result = apply_graphify_configure(plan)

    receipt = result.record.receipt_for(CONFIGURE_STEP_ID)
    assert receipt is not None
    assert receipt.configuration_ownership
    patch = receipt.configuration_ownership[0]
    assert patch.tool_id == "graphify"
    assert patch.relative_path == ".codex/config.toml"


def test_configure_blocked_when_codex_parent_absent(project, plan):
    """When .codex/ does not exist, configure must return blocked without creating files."""
    from stackwinnow.adapters.graphify_configure import apply_graphify_configure

    _seed_install_and_index(project)

    result = apply_graphify_configure(plan)

    assert not result.configured
    assert result.results and result.results[0].status == OperationStatus.BLOCKED
    assert not (project / ".codex").exists()


def test_configure_no_op_when_already_configured(project, plan):
    """Calling configure a second time when entry already matches must skip without error."""
    from stackwinnow.adapters.graphify_configure import apply_graphify_configure

    _seed_install_and_index(project)
    (project / ".codex").mkdir()

    first = apply_graphify_configure(plan)
    assert first.configured

    second = apply_graphify_configure(plan)
    assert not second.configured or second.results[0].status in (
        OperationStatus.SKIPPED,
        OperationStatus.SUCCEEDED,
    )


# ---------------------------------------------------------------------------
# 5. graphify_plan no longer has the Codex config blocker
# ---------------------------------------------------------------------------


def test_graphify_plan_does_not_include_codex_config_blocker(plan):
    """After B05, the execution plan must not list Codex configuration as not implemented."""
    for blocker in plan.blockers:
        assert "codex configuration" not in blocker.lower() or "not implemented" not in blocker.lower(), (
            f"Unexpected Codex config blocker: {blocker!r}"
        )

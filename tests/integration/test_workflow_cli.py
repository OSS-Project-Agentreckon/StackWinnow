"""One actual installed CLI workflow smoke; full profile combinations belong to A05."""

import shutil

import pytest
from test_foundation_cli import assert_functional_report
from test_foundation_cli import journey as foundation_journey

pytestmark = pytest.mark.integration


@pytest.fixture
def journey(fixture_project, tmp_path, subprocess_env):
    return foundation_journey.__wrapped__(fixture_project, tmp_path, subprocess_env)


def test_real_deterministic_workflow_cli(journey):
    if shutil.which("node") is None or shutil.which("npm") is None:
        pytest.skip("Requires working Node 24 and npm.")
    j, root = journey, journey.root
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    discovery = j.call("workflow", "inspect", root, "--goal", "evaluation", "--json")
    assert len(discovery["executable_modes"]) == 4
    plan = j.plan("workflow", "workflow", "plan", root, "--tool", "promptfoo")
    dry = j.call("workflow", "apply", plan, "--dry-run", "--json")
    assert dry["dry_run"] and not dry["ready"] and not (root / ".stackwinnow").exists()
    result = j.call("workflow", "apply", plan, "--json")
    assert result["ready"] and result["status"] == "succeeded"
    assert [p["phase"] for p in result["outcomes"]] == ["promptfoo", "verify"]
    evidence = assert_functional_report(result["verification"], ["promptfoo"], "pass")
    assert all((root / path).is_file() for path in evidence)
    assert not result["passive_status"]["run_functional"] and not result["passive_status"]["ready"]
    status = j.call("workflow", "status", root, "--tool", "promptfoo", "--json", code=1)
    assert not status["run_functional"] and not status["ready"]
    for path, raw in before.items():
        assert (root / path).read_bytes() == raw


def test_real_graphify_workflow_cli(journey):
    import json
    import sys

    from test_foundation_cli import EXPECTATION

    if sys.version_info[:2] != (3, 11) or shutil.which("codex") is None:
        pytest.skip("Requires the locked CPython 3.11 target and Codex CLI 0.169.0.")
    j, root = journey, journey.root
    expected = j.output / "expected.json"
    expected.write_text(json.dumps(EXPECTATION))
    plan = j.plan(
        "workflow", "workflow", "plan", root, "--tool", "graphify", "--expectation", expected
    )
    result = j.call("workflow", "apply", plan, "--json")
    assert result["ready"] and result["status"] == "succeeded"
    assert [p["phase"] for p in result["outcomes"]] == [
        "graphify-runtime",
        "graphify-index",
        "graphify-configure",
        "verify",
    ]
    assert_functional_report(result["verification"], ["graphify"], "pass")
    assert not result["passive_status"]["run_functional"]
    assert not result["passive_status"]["ready"]

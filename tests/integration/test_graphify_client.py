"""Real managed Graphify and actual Codex tool invocation; no paid provider."""

import json
import platform
import shutil

import pytest

from stackwinnow.adapters.graphify import RelationshipExpectation
from stackwinnow.adapters.graphify_configure import (
    apply_graphify_configure,
    plan_graphify_configure,
)
from stackwinnow.adapters.graphify_index import apply_graphify_index, plan_graphify_index
from stackwinnow.adapters.graphify_install import apply_graphify_install
from stackwinnow.adapters.graphify_plan import plan_graphify_execution
from stackwinnow.verify import check_project

pytestmark = pytest.mark.integration


def test_real_managed_graphify_codex_positive_repeat_and_negative(fixture_project):
    if (
        platform.system() != "Darwin"
        or platform.machine() != "arm64"
        or not platform.python_version().startswith("3.11.")
    ):
        pytest.skip("Graphify lock targets CPython3.11/macOS arm64.")
    if not shutil.which("codex"):
        pytest.skip("Codex CLI0.169.0 is required.")
    root = fixture_project.root.resolve()
    (root / ".codex").mkdir()
    config = root / ".codex/config.toml"
    original = '# user comment\n[mcp_servers.other]\ncommand = "/do-not-start"\n'
    config.write_text(original)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file() and p != config}
    expectation = RelationshipExpectation(
        caller_file="sample_app/greetings.py",
        caller_label="greet()",
        callee_file="sample_app/names.py",
        callee_label="normalize_name()",
    )
    execution = plan_graphify_execution(root, expectation=expectation)
    installed = apply_graphify_install(execution)
    assert installed.installed, installed.model_dump_json()
    indexed = apply_graphify_index(plan_graphify_index(root, expectation=expectation))
    assert indexed.indexed, indexed.model_dump_json()
    plan = plan_graphify_configure(root)
    assert apply_graphify_configure(plan).configured
    assert config.read_text().startswith(original)
    config_bytes = config.read_bytes()
    passive = check_project(root, tool_ids=["graphify"])
    assert not passive.ready
    evidence = []
    for scenario in ("pass", "fail", "pass"):
        report = check_project(root, tool_ids=["graphify"], run_functional=True, scenario=scenario)
        states = {c.kind: c for c in report.tools[0].checks}
        assert states["installed"].status == states["configured"].status == "succeeded"
        assert states["connected"].status == "succeeded", report.as_payload()
        assert report.ready == (scenario == "pass"), report.as_payload()
        path = root / states["functional"].evidence[0].source
        payload = json.loads(path.read_text())
        assert payload["provider"] == "scripted-loopback" and payload["provider_requests"] == 2
        assert len(payload["calls"]) == 1 and payload["calls"][0]["tool"] == "query_relationship"
        assert payload["inputs_current"]
        evidence.append(path)
    assert len(set(evidence)) == 3
    assert apply_graphify_configure(plan).configured
    assert apply_graphify_install(execution).installed
    assert config.read_bytes() == config_bytes
    assert all(path.read_bytes() == raw for path, raw in before.items())

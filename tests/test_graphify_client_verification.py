import json

import pytest
from test_graphify_bridge import indexed as _indexed_fixture
from test_graphify_index_adapter import project as _project_fixture

from stackwinnow.adapters.graphify_configure import (
    apply_graphify_configure,
    plan_graphify_configure,
)
from stackwinnow.configure.codex import GRAPHIFY_SERVER
from stackwinnow.graphify_bridge import TOOL
from stackwinnow.installer import load_record
from stackwinnow.verify import check_project
from stackwinnow.verify import graphify_client as client

project = _project_fixture
indexed = _indexed_fixture


@pytest.fixture
def configured(indexed):
    assert apply_graphify_configure(plan_graphify_configure(indexed)).configured
    return indexed


def test_only_completed_matching_mcp_result_establishes_client_success():
    expected = {"relationship_found": True}
    arguments = {"caller_label": "call()"}
    call = {
        "type": "mcp_tool_call",
        "server": GRAPHIFY_SERVER,
        "tool": TOOL,
        "arguments": arguments,
        "status": "completed",
        "result": {"content": [{"type": "text", "text": json.dumps(expected)}], "isError": False},
    }
    events = [{"type": "item.completed", "item": call}, {"type": "turn.completed"}]

    def observed():
        return client.client_observations(
            "\n".join(json.dumps(e) for e in events), arguments, expected
        )

    assert observed()[:2] == (True, True)
    call["result"]["isError"] = True
    assert observed()[:2] == (True, False)
    del call["result"]["isError"]
    call["result"]["content"][0]["text"] = "plain text tool error"
    assert observed()[:2] == (True, False)
    call["status"] = "failed"
    assert observed()[:2] == (True, False)
    call["status"] = "completed"
    call["server"] = "foreign"
    assert observed()[:2] == (False, False)
    events[:] = [
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Success!"}},
        {"type": "turn.completed"},
    ]
    assert observed()[:2] == (False, False)


def test_malformed_duplicate_or_wrong_result_cannot_pass():
    for raw in ("[]", "null", "invalid", '{"type":"item.completed","item":null}'):
        assert client.client_observations(raw, {}, {})[:2] == (False, False)
    call = {
        "type": "mcp_tool_call",
        "server": GRAPHIFY_SERVER,
        "tool": TOOL,
        "arguments": {},
        "status": "completed",
        "result": {"content": [{"type": "text", "text": "{}"}]},
    }
    raw = json.dumps({"type": "item.completed", "item": call})
    assert client.client_observations(raw + "\n" + raw, {}, {})[:2] == (False, False)


def test_configured_status_never_reuses_historical_connection(configured, monkeypatch):
    monkeypatch.setattr(client, "run_client_check", lambda *a, **k: pytest.fail("client ran"))
    before = (configured / ".stackwinnow/receipts.json").read_bytes()
    report = check_project(configured, tool_ids=["graphify"])
    states = {c.kind: c.status for c in report.tools[0].checks}
    assert states == {
        "installed": "succeeded",
        "configured": "succeeded",
        "connected": "not_run",
        "functional": "not_run",
    }
    assert not report.ready
    assert (configured / ".stackwinnow/receipts.json").read_bytes() == before


def test_client_runs_outside_lock_with_durable_intent_and_fresh_outcome(configured, monkeypatch):
    scenarios = []

    def check(root, settings, expected, **kwargs):
        assert not (root / ".stackwinnow/operation.lock").exists()
        assert load_record(str(root)).steps[-1].status == "failed"
        assert load_record(str(root)).steps[-1].step_id.startswith("graphify-client-")
        scenarios.append(kwargs["scenario"])
        return {"connected": True, "functional": kwargs["scenario"] == "pass", "calls": []}

    monkeypatch.setattr(client, "run_client_check", check)
    for scenario in ("pass", "fail", "pass"):
        report = check_project(
            configured, tool_ids=["graphify"], run_functional=True, scenario=scenario
        )
        assert report.ready == (scenario == "pass")
        states = {c.kind: c for c in report.tools[0].checks}
        assert states["connected"].status == "succeeded"
        proof = json.loads((configured / states["functional"].evidence[0].source).read_text())
        assert proof["inputs_current"]
    assert scenarios == ["pass", "fail", "pass"]
    receipts = [
        r for r in load_record(str(configured)).steps if r.step_id.startswith("graphify-client-")
    ]
    assert [r.status for r in receipts] == ["succeeded", "failed", "succeeded"]


def test_mid_client_source_change_prevents_current_functional_success(configured, monkeypatch):
    def changed(root, *args, **kwargs):
        (root / "caller.py").write_text("changed")
        return {"connected": True, "functional": True}

    monkeypatch.setattr(client, "run_client_check", changed)
    report = check_project(configured, tool_ids=["graphify"], run_functional=True)
    assert not report.ready
    assert next(c for c in report.tools[0].checks if c.kind == "functional").status == "failed"


def test_missing_codex_is_failure_not_stale_success(configured, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("Codex is unavailable")

    monkeypatch.setattr(client, "run_client_check", fail)
    report = check_project(configured, tool_ids=["graphify"], run_functional=True)
    assert report.status == "failed" and not report.ready
    assert load_record(str(configured)).steps[-1].status == "failed"

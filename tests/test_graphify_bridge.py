import io
import json

import pytest
from test_graphify_index_adapter import (
    EXPECTATION,
    _good_runner,
    _seed_install,
)
from test_graphify_index_adapter import project as _project_fixture

from stackwinnow import graphify_bridge as bridge
from stackwinnow.adapters.graphify import GraphifyError
from stackwinnow.adapters.graphify_index import apply_graphify_index, plan_graphify_index
from stackwinnow.adapters.graphify_plan import ENV_PATH
from stackwinnow.runner import CommandResult
from stackwinnow.state.lock import project_lock

project = _project_fixture


@pytest.fixture
def indexed(project):
    _seed_install(project)
    plan = plan_graphify_index(project, expectation=EXPECTATION)
    assert apply_graphify_index(plan, command_runner=_good_runner()).indexed
    return project


def test_query_uses_current_owned_graph_and_fixed_argv(indexed):
    calls = []

    def run(argv, **kwargs):
        assert (indexed / ".stackwinnow/operation.lock").exists()
        calls.append(argv)
        return CommandResult(0, "path found", "")

    value = bridge.query_relationship(
        indexed, str(indexed / ENV_PATH / "bin/python"), EXPECTATION.model_dump(), runner=run
    )
    assert value["relationship_found"] and value["source_node_id"] == "caller"
    assert value["query_returncode"] == 0
    assert len(calls) == 1 and calls[0][1:5] == ["-B", "-I", "-m", "graphify"]
    assert "--directed" in calls[0]


@pytest.mark.parametrize("change", ["source", "runtime", "graph", "wrong-python", "wrong-edge"])
def test_query_never_runs_on_changed_or_unexpected_inputs(indexed, change):
    python = str(indexed / ENV_PATH / "bin/python")
    args = EXPECTATION.model_dump()
    if change == "source":
        (indexed / "callee.py").write_text("changed")
    elif change == "runtime":
        (indexed / ENV_PATH / "bin/python").write_text("changed")
    elif change == "graph":
        (indexed / bridge.GRAPH_PATH).write_text("{}")
    elif change == "wrong-python":
        python = "/external/python"
    else:
        args["callee_label"] = "missing()"
    with pytest.raises(GraphifyError):
        bridge.query_relationship(indexed, python, args, runner=lambda *a, **k: pytest.fail("ran"))


def test_query_failed_upstream_and_mid_query_source_change_fail(indexed):
    python = str(indexed / ENV_PATH / "bin/python")
    with pytest.raises(GraphifyError):
        bridge.query_relationship(
            indexed,
            python,
            EXPECTATION.model_dump(),
            runner=lambda *a, **k: CommandResult(4, "", ""),
        )

    def changed(*args, **kwargs):
        (indexed / "callee.py").write_text("changed")
        return CommandResult(0, "", "")

    with pytest.raises(GraphifyError):
        bridge.query_relationship(indexed, python, EXPECTATION.model_dump(), runner=changed)


def exchange(messages, *, query=None):
    raw = b"".join(json.dumps(m).encode() + b"\n" for m in messages)
    output = io.StringIO()
    status = bridge.serve(None, "unused", io.BytesIO(raw), output, query=query)
    return status, [json.loads(line) for line in output.getvalue().splitlines()]


def request(method, params=None, identifier=1):
    return {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params or {}}


def test_mcp_initialize_list_call_and_notification():
    messages = [
        request("initialize", {"protocolVersion": "2025-03-26"}),
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        request("tools/list", identifier=2),
        request("tools/call", {"name": bridge.TOOL, "arguments": EXPECTATION.model_dump()}, 3),
    ]
    status, responses = exchange(messages, query=lambda *a: {"relationship_found": True})
    assert status == 0 and len(responses) == 3
    assert responses[0]["result"]["protocolVersion"] == "2025-03-26"
    assert responses[1]["result"]["tools"] == [bridge.TOOL_SCHEMA]
    assert not responses[2]["result"]["isError"]


def test_mcp_protocol_errors_and_tool_failure_are_structured():
    def fail(*args):
        raise GraphifyError("private filesystem details")

    status, responses = exchange(
        [
            request("tools/list"),
            [],
            request("initialize"),
            request("unknown"),
            request("tools/call", {"name": "shell", "arguments": {}}),
            request("tools/call", {"name": bridge.TOOL, "arguments": {}}),
        ],
        query=fail,
    )
    assert status == 0
    assert [r["error"]["code"] for r in responses[:2]] == [-32000, -32600]
    assert responses[3]["error"]["code"] == -32601
    assert responses[4]["error"]["code"] == -32602
    assert responses[5]["result"]["isError"]
    assert "private filesystem" not in json.dumps(responses)


def test_mcp_rejects_duplicate_keys_and_oversized_input():
    output = io.StringIO()
    bridge.serve(None, "", io.BytesIO(b'{"method":"ping","method":"initialize"}\n'), output)
    assert json.loads(output.getvalue())["error"]["code"] == -32700
    output = io.StringIO()
    assert bridge.serve(None, "", io.BytesIO(b"x" * (bridge.MAX_MESSAGE_BYTES + 1)), output) == 2


def test_busy_project_returns_tool_failure_without_nested_lock(indexed):
    from stackwinnow.state.lock import ProjectLockError

    with project_lock(indexed), pytest.raises(ProjectLockError):
        bridge.query_relationship(
            indexed, str(indexed / ENV_PATH / "bin/python"), EXPECTATION.model_dump()
        )

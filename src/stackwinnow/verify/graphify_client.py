"""Actual Codex -> manager MCP bridge -> upstream Graphify acceptance.

The model decisions come from a scripted loopback provider. This proves client
routing and tool results, not model quality or paid-provider token consumption.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

from stackwinnow.adapters.graphify import _environment
from stackwinnow.adapters.graphify_configure import registration_digest
from stackwinnow.configure.codex import (
    GRAPHIFY_SERVER,
    apply_graphify_codex_server,
    plan_graphify_codex_server,
)
from stackwinnow.graphify_bridge import TOOL
from stackwinnow.runner import run_command

CODEX_VERSION = "0.169.0"


def client_observations(stdout: str, arguments: dict, expected: dict) -> tuple[bool, bool, list]:
    """Only a completed selected MCP event establishes connectivity or success."""
    try:
        events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        calls = [
            e["item"]
            for e in events
            if e.get("type") == "item.completed"
            and e.get("item", {}).get("type") == "mcp_tool_call"
            and e["item"].get("server") == GRAPHIFY_SERVER
        ]
        if len(calls) != 1:
            return False, False, calls
        call = calls[0]
        result = call.get("result")
        connected = (
            call.get("tool") == TOOL
            and call.get("arguments") == arguments
            and call.get("status") in ("completed", "failed")
            and not call.get("error")
            and isinstance(result, dict)
            and bool(result.get("content"))
        )
        if not connected:
            return False, False, calls
        try:
            texts = [c["text"] for c in result["content"] if c.get("type") == "text"]
            functional = (
                call.get("status") == "completed"
                and not result.get("isError", False)
                and len(texts) == 1
                and json.loads(texts[0]) == expected
                and any(e.get("type") == "turn.completed" for e in events)
            )
        except (ValueError, TypeError, KeyError, AttributeError):
            # A routed result establishes connection even if its content cannot
            # establish the expected relationship (including plain-text errors).
            functional = False
        return True, bool(functional), calls
    except (ValueError, TypeError, KeyError, AttributeError):
        return False, False, []


def run_client_check(
    root: Path, registration: dict, expected: dict, *, runner=run_command, scenario="pass"
) -> dict:
    """Run outside the project lock: the bridge acquires it for each MCP query."""
    if scenario not in ("pass", "fail"):
        raise ValueError("Unknown Graphify fixture scenario.")
    codex = shutil.which("codex")
    if not codex:
        raise ValueError("Codex CLI 0.169.0 is required for client verification.")
    nonce = uuid4().hex
    arguments = dict(expected["expectation"])
    if scenario == "fail":
        arguments["callee_label"] += "__missing_" + nonce
    state = {"requests": 0, "error": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if self.path != "/v1/responses" or not 0 < length <= 4 * 1024 * 1024:
                    raise ValueError("Unsupported fixture request.")
                request = json.loads(self.rfile.read(length))
                index = state["requests"]
                if index > 1:
                    raise ValueError("Unexpected extra model request.")
                state["requests"] += 1
                if index == 0:
                    names = {
                        tool["name"]
                        for ns in request.get("tools", [])
                        if ns.get("name") == "mcp__" + GRAPHIFY_SERVER
                        for tool in ns.get("tools", [])
                    }
                    if TOOL not in names:
                        raise ValueError("Codex did not expose the selected Graphify tool.")
                    item = {
                        "type": "function_call",
                        "id": "fc_0",
                        "call_id": "call_0",
                        "namespace": "mcp__" + GRAPHIFY_SERVER,
                        "name": TOOL,
                        "arguments": json.dumps(arguments),
                        "status": "completed",
                    }
                else:
                    item = {
                        "type": "message",
                        "id": "msg_1",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Graphify client fixture ended.",
                                "annotations": [],
                            }
                        ],
                    }
                response = {
                    "id": "resp_" + str(index),
                    "object": "response",
                    "status": "completed",
                    "output": [item],
                    "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                }
                events = [
                    {
                        "type": "response.created",
                        "response": dict(response, status="in_progress", output=[]),
                    },
                    {"type": "response.output_item.added", "output_index": 0, "item": item},
                    {"type": "response.output_item.done", "output_index": 0, "item": item},
                    {"type": "response.completed", "response": response},
                ]
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for event in events:
                    self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                state["error"] = True
                self.send_error(400)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="sw-graphify-client-", dir="/tmp") as temporary:
                scratch = Path(temporary).resolve()
                project = scratch / "project"
                (project / ".codex").mkdir(parents=True)
                applied = apply_graphify_codex_server(
                    plan_graphify_codex_server(project, registration)
                )
                if applied.result.status != "succeeded":
                    raise ValueError("Cannot stage the selected registration.")
                home, client_home = scratch / "home", scratch / "codex"
                home.mkdir()
                client_home.mkdir()
                config = (
                    'model_provider = "stackwinnow_fixture"\nmodel = "fixture-model"\nweb_search = "disabled"\n'
                    "[features]\nplugins = false\nremote_plugin = false\napps = false\nshell_snapshot = false\n"
                    "shell_tool = false\ndaemon_auto_start = false\nskill_search = false\nskip_host_skill_discovery = true\n"
                    '[model_providers.stackwinnow_fixture]\nname = "StackWinnow fixture"\n'
                    f'base_url = "http://127.0.0.1:{server.server_port}/v1"\n'
                    'wire_api = "responses"\nrequires_openai_auth = false\n'
                    "[projects." + json.dumps(str(project)) + ']\ntrust_level = "trusted"\n'
                )
                (client_home / "config.toml").write_text(config)
                env = dict(
                    _environment(root),
                    HOME=str(home),
                    CODEX_HOME=str(client_home),
                    TMPDIR=str(scratch),
                    TMP=str(scratch),
                    TEMP=str(scratch),
                )
                version = runner([codex, "--version"], cwd=scratch, timeout=15, extra_env=env)
                if not version.succeeded or version.stdout.strip() != "codex-cli " + CODEX_VERSION:
                    raise ValueError("A working Codex CLI 0.169.0 is required.")
                outcome = runner(
                    [
                        codex,
                        "exec",
                        "--ephemeral",
                        "--skip-git-repo-check",
                        "--ignore-rules",
                        "--sandbox",
                        "danger-full-access",
                        "-C",
                        str(project),
                        "--json",
                        "Exercise the selected Graphify relationship tool.",
                    ],
                    cwd=project,
                    timeout=120,
                    extra_env=env,
                )
        finally:
            server.shutdown()
            thread.join(timeout=2)
    connected, functional, calls = client_observations(outcome.stdout, arguments, expected)
    functional = functional and outcome.succeeded and not state["error"] and state["requests"] == 2
    return {
        "schema_version": 1,
        "client": "codex",
        "client_version": CODEX_VERSION,
        "scope": "isolated-client-selected-registration",
        "provider": "scripted-loopback",
        "scenario": scenario,
        "connected": connected,
        "functional": functional,
        "returncode": outcome.returncode,
        "timed_out": outcome.timed_out,
        "registration_sha256": registration_digest(registration),
        "calls": calls,
        "provider_requests": state["requests"],
        "check_id": nonce,
    }

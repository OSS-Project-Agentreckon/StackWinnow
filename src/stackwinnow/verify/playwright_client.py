"""Actual Codex -> MCP -> Chromium check with scripted local model decisions.

This is client integration evidence, not a model-quality or hosted-provider test.
Only the selected server registration is copied into an isolated client project.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

from stackwinnow.configure.codex import SERVER, apply_codex_server, plan_codex_server
from stackwinnow.runner import run_command

READ_RESULT = '() => ({url: location.href, result: document.querySelector("#result").textContent})'
TOOLS = ("browser_navigate", "browser_click", "browser_evaluate")


def client_observations(stdout: str, url: str, expected: str) -> tuple[bool, bool, list[dict]]:
    """Accept only completed MCP results, never a model's final success claim."""
    try:
        events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        calls = [
            e["item"]
            for e in events
            if e.get("type") == "item.completed"
            and e.get("item", {}).get("type") == "mcp_tool_call"
            and e["item"].get("server") == SERVER
        ]
        by_tool = {item["tool"]: item for item in calls}
        navigate = by_tool.get("browser_navigate", {})
        connected = (
            navigate.get("status") == "completed"
            and navigate.get("arguments") == {"url": url}
            and not navigate.get("error")
            and isinstance(navigate.get("result"), dict)
            and bool(navigate["result"].get("content"))
        )
        if not connected or len(calls) != 3 or tuple(c["tool"] for c in calls) != TOOLS:
            return bool(connected), False, calls
        if any(
            c.get("status") != "completed"
            or c.get("error")
            or not isinstance(c.get("result"), dict)
            for c in calls
        ):
            return True, False, calls
        if by_tool["browser_click"].get("arguments") != {
            "element": "Complete check",
            "target": "#complete-check",
        }:
            return True, False, calls
        evaluation = by_tool["browser_evaluate"]
        if evaluation.get("arguments") != {"function": READ_RESULT}:
            return True, False, calls
        texts = [c["text"] for c in evaluation["result"]["content"] if c.get("type") == "text"]
        if len(texts) != 1 or not texts[0].startswith("### Result\n"):
            return True, False, calls
        value, _ = json.JSONDecoder().raw_decode(texts[0][len("### Result\n") :])
        passed = value == {"url": url, "result": expected} and any(
            e.get("type") == "turn.completed" for e in events
        )
        return True, passed, calls
    except (ValueError, KeyError, TypeError, AttributeError):
        return False, False, []


def run_client_check(
    root: Path, registration: dict, codex: str, *, runner=run_command, scenario: str = "pass"
) -> dict:
    from stackwinnow.adapters._managed import directories
    from stackwinnow.adapters.playwright_mcp import STATE, environment

    if scenario not in ("pass", "fail"):
        raise ValueError("Unknown fixture scenario.")
    nonce = uuid4().hex
    expected = "StackWinnow fixture passed " + nonce
    source = (
        files("stackwinnow").joinpath("data/playwright-fixture.html").read_text(encoding="utf-8")
    )
    source = source.replace(
        "StackWinnow fixture passed",
        expected if scenario == "pass" else "Negative control: button did not complete the check",
    )
    state = {"requests": 0, "page_requests": 0, "error": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_GET(self):
            if self.path != "/fixture/" + nonce:
                self.send_error(404)
                return
            state["page_requests"] += 1
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(source.encode("utf-8"))

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if self.path != "/v1/responses" or not 0 < length <= 4 * 1024 * 1024:
                    raise ValueError("Unsupported local provider request.")
                request = json.loads(self.rfile.read(length))
                index = state["requests"]
                if index > 3:
                    raise ValueError("Unexpected extra model request.")
                state["requests"] += 1
                if index < 3:
                    names = {
                        tool["name"]
                        for ns in request.get("tools", [])
                        if ns.get("name") == "mcp__" + SERVER
                        for tool in ns.get("tools", [])
                    }
                    if not set(TOOLS) <= names:
                        raise ValueError("Codex did not expose the selected MCP tools.")
                    arguments = (
                        {"url": url},
                        {"element": "Complete check", "target": "#complete-check"},
                        {"function": READ_RESULT},
                    )[index]
                    item = {
                        "type": "function_call",
                        "id": f"fc_{index}",
                        "call_id": f"call_{index}",
                        "namespace": "mcp__" + SERVER,
                        "name": TOOLS[index],
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
                                "text": "Client fixture sequence ended.",
                                "annotations": [],
                            }
                        ],
                    }
                response = {
                    "id": f"resp_{index}",
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
            except (OSError, ValueError, KeyError, TypeError):
                state["error"] = True
                self.send_error(400)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        server.daemon_threads = True
        url = f"http://127.0.0.1:{server.server_port}/fixture/{nonce}"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            # Outside the selected project/ancestors: no other MCP servers, rules,
            # providers or personal trust/auth files are loaded by the client.
            with tempfile.TemporaryDirectory(prefix="sw-client-", dir="/tmp") as temporary:
                scratch = Path(temporary).resolve()
                project = scratch / "project"
                (project / ".codex").mkdir(parents=True)
                applied = apply_codex_server(plan_codex_server(project, registration))
                if applied.result.status != "succeeded":
                    raise ValueError("Could not stage selected client registration.")
                home = scratch / "home"
                home.mkdir()
                client_home = scratch / "codex"
                client_home.mkdir()
                config = (
                    'model_provider = "stackwinnow_fixture"\nmodel = "fixture-model"\n'
                    'web_search = "disabled"\n'
                    "[features]\nplugins = false\nremote_plugin = false\napps = false\n"
                    "shell_snapshot = false\nshell_tool = false\ndaemon_auto_start = false\n"
                    "skill_search = false\nskip_host_skill_discovery = true\n"
                    '[model_providers.stackwinnow_fixture]\nname = "StackWinnow local fixture"\n'
                    f'base_url = "http://127.0.0.1:{server.server_port}/v1"\n'
                    'wire_api = "responses"\nrequires_openai_auth = false\n'
                    "[projects." + json.dumps(str(project)) + ']\ntrust_level = "trusted"\n'
                )
                (client_home / "config.toml").write_text(config, encoding="utf-8")
                env = environment(root, registration["command"])
                env.update(
                    HOME=str(home),
                    CODEX_HOME=str(client_home),
                    TMPDIR=str(scratch),
                    TMP=str(scratch),
                    TEMP=str(scratch),
                )
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
                        "Exercise the selected browser tools against the local fixture.",
                    ],
                    cwd=project,
                    timeout=120,
                    extra_env=env,
                )
        finally:
            server.shutdown()
            thread.join(timeout=2)
    connected, functional, calls = client_observations(outcome.stdout, url, expected)
    functional = (
        functional and outcome.succeeded and not state["error"] and state["page_requests"] > 0
    )
    report = {
        "schema_version": 1,
        "client": "codex",
        "scope": "isolated-client-selected-registration",
        "provider": "scripted-loopback",
        "scenario": scenario,
        "connected": connected,
        "functional": functional,
        "returncode": outcome.returncode,
        "timed_out": outcome.timed_out,
        "registration_sha256": hashlib.sha256(
            json.dumps(registration, sort_keys=True).encode()
        ).hexdigest(),
        "calls": calls,
        "fixture_requests": state["page_requests"],
        "message": "Codex invoked Playwright and observed the fresh fixture result."
        if functional
        else "Codex fixture check failed; inspect the local evidence. No hosted provider was called.",
    }
    directory = directories(root, STATE + "/checks", create=True)
    path = directory / (nonce + ".json")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
    report["evidence_path"] = str(path)
    return report

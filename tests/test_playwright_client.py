import copy
import json

import pytest

from stackwinnow.verify.playwright_client import READ_RESULT, client_observations

URL = "http://127.0.0.1:4321/fixture/fresh"
EXPECTED = "StackWinnow fixture passed fresh"


def events():
    calls = []
    for tool, args in (
        ("browser_navigate", {"url": URL}),
        ("browser_click", {"element": "Complete check", "target": "#complete-check"}),
        ("browser_evaluate", {"function": READ_RESULT}),
    ):
        text = (
            "### Result\n" + json.dumps({"url": URL, "result": EXPECTED})
            if tool == "browser_evaluate"
            else "Tool completed."
        )
        calls.append(
            {
                "type": "item.completed",
                "item": {
                    "type": "mcp_tool_call",
                    "server": "stackwinnow_playwright",
                    "tool": tool,
                    "arguments": args,
                    "status": "completed",
                    "error": None,
                    "result": {"content": [{"type": "text", "text": text}]},
                },
            }
        )
    return calls + [{"type": "turn.completed"}]


def observe(items):
    return client_observations("\n".join(json.dumps(x) for x in items), URL, EXPECTED)


def test_client_evidence_requires_actual_tool_results():
    assert observe(events())[:2] == (True, True)
    assert observe(
        [
            {"type": "item.completed", "item": {"type": "agent_message", "text": EXPECTED}},
            {"type": "turn.completed"},
        ]
    )[:2] == (False, False)


@pytest.mark.parametrize(
    "mutation",
    [
        "failed-click",
        "missing-click",
        "wrong-server",
        "stale-nonce",
        "wrong-url",
        "wrong-function",
        "duplicate",
        "no-turn",
        "not-json",
        "error",
    ],
)
def test_incomplete_or_forged_success_claims_fail(mutation):
    items = copy.deepcopy(events())
    if mutation == "failed-click":
        items[1]["item"]["status"] = "failed"
    elif mutation == "missing-click":
        del items[1]
    elif mutation == "wrong-server":
        items[2]["item"]["server"] = "other"
    elif mutation == "stale-nonce":
        items[2]["item"]["result"]["content"][0]["text"] = "### Result\n" + json.dumps(
            {"url": URL, "result": "StackWinnow fixture passed old"}
        )
    elif mutation == "wrong-url":
        items[0]["item"]["arguments"]["url"] = "https://example.com"
    elif mutation == "wrong-function":
        items[2]["item"]["arguments"]["function"] = '() => "StackWinnow fixture passed fresh"'
    elif mutation == "duplicate":
        items.insert(1, items[0])
    elif mutation == "no-turn":
        items.pop()
    elif mutation == "error":
        items[1]["item"]["error"] = {"message": "failed"}
    else:
        items[2]["item"]["result"]["content"][0]["text"] = EXPECTED
    assert observe(items)[1] is False


def test_malformed_client_output():
    assert client_observations("not json", URL, EXPECTED)[:2] == (False, False)


def test_missing_navigation_result_is_not_connectivity():
    items = events()
    items[0]["item"]["result"] = None
    assert observe(items)[:2] == (False, False)


def test_isolated_client_disables_plugin_refresh_and_personal_state(tmp_path):
    import tomllib
    from pathlib import Path

    from stackwinnow.adapters.playwright_mcp import settings
    from stackwinnow.runner import CommandResult
    from stackwinnow.verify.playwright_client import run_client_check

    homes = []

    def runner(args, *, cwd, extra_env, **kwargs):
        home = Path(extra_env["CODEX_HOME"])
        homes.append(home.parent)
        assert not home.is_relative_to(tmp_path)
        config = tomllib.loads((home / "config.toml").read_text())
        for flag in (
            "plugins",
            "remote_plugin",
            "apps",
            "shell_snapshot",
            "shell_tool",
            "daemon_auto_start",
            "skill_search",
        ):
            assert config["features"][flag] is False
        assert config["features"]["skip_host_skill_discovery"] is True
        assert config["web_search"] == "disabled"
        assert not (home / "auth.json").exists()
        assert "OPENAI_API_KEY" not in extra_env
        project_config = tomllib.loads((Path(cwd) / ".codex/config.toml").read_text())
        assert set(project_config["mcp_servers"]) == {"stackwinnow_playwright"}
        return CommandResult(0, '{"type":"turn.completed"}\n', "")

    report = run_client_check(
        tmp_path, settings(tmp_path, "/runtime/node"), "/runtime/codex", runner=runner
    )
    assert not report["functional"]
    assert all(not path.exists() for path in homes)
    assert Path(report["evidence_path"]).exists()

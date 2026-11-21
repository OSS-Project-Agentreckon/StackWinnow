"""Real npm/browser downloads and Codex CLI; no provider key or paid model call."""

import json
import platform
import shutil
from pathlib import Path

import pytest

from stackwinnow.adapters import playwright_mcp as adapter
from stackwinnow.runner import run_command
from stackwinnow.verify import check_project

pytestmark = pytest.mark.integration


def test_real_codex_browser_onboarding_repeat_and_negative(fixture_project):
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        pytest.skip("Playwright recipe currently requires macOS arm64.")
    if not all(shutil.which(tool) for tool in ("node", "npm", "codex")):
        pytest.skip("Install Node 24, npm and Codex CLI 0.169.0.")
    root = fixture_project.root.resolve()
    (root / ".codex").mkdir()
    config = root / ".codex/config.toml"
    original = '# preserve\n[mcp_servers.unrelated]\ncommand = "/do-not-start"\n'
    config.write_text(original)
    (root / ".npmrc").write_text("registry=http://127.0.0.1:9/do-not-use\n")
    (root / "package.json").write_text('{"private":true,"name":"preserve"}\n')
    snapshots = {
        p: p.read_bytes()
        for p in (fixture_project.settings, root / ".npmrc", root / "package.json")
    }
    commands = []

    def runner(args, **kwargs):
        commands.append(args)
        assert "OPENAI_API_KEY" not in kwargs.get("extra_env", {})
        return run_command(args, **kwargs)

    first = adapter.apply_playwright(
        adapter.plan_playwright(root, assistant="codex"), command_runner=runner
    )
    assert first.status == "succeeded", first.model_dump_json(indent=2)
    assert first.client_check["functional"]
    assert config.read_text().startswith(original)
    before = config.read_bytes()
    count = len(commands)
    report = check_project(root, tool_ids=["playwright-mcp"], command_runner=runner)
    assert not report.ready
    assert len(commands) == count
    negative = check_project(
        root,
        tool_ids=["playwright-mcp"],
        run_functional=True,
        scenario="fail",
        command_runner=runner,
    )
    assert str(negative.status) == "failed", negative.as_payload()
    assert negative.tools[0].checks[2].status == "succeeded"  # connected, but negative DOM
    repeat = adapter.apply_playwright(
        adapter.plan_playwright(root, assistant="codex"), command_runner=runner
    )
    assert repeat.status == "succeeded", repeat.model_dump_json(indent=2)
    assert sum("install" in args for args in commands) == 2  # npm + one browser download
    assert config.read_bytes() == before
    assert all(p.read_bytes() == raw for p, raw in snapshots.items())
    for check in (first.client_check, repeat.client_check):
        evidence = json.loads(Path(check["evidence_path"]).read_text())
        assert [c["tool"] for c in evidence["calls"]] == [
            "browser_navigate",
            "browser_click",
            "browser_evaluate",
        ]
        assert evidence["provider"] == "scripted-loopback"
    assert first.client_check["evidence_path"] != repeat.client_check["evidence_path"]

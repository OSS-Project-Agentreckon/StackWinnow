"""User discovery journeys and execution boundaries through the public CLI."""

import json

import pytest
from test_cli import run_cli
from test_recommendations import conflict_catalog
from test_workflow import project as project

from stackwinnow import cli


def snapshot(root):
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    }


@pytest.mark.parametrize("preference", ["local", "hosted"])
def test_mixed_project_explains_declarations_goals_and_selection_order(
    tmp_path, capsys, preference
):
    (tmp_path / "pyproject.toml").write_text("""[project]
name = "sample"
dependencies = ["Headroom_AI>=0.1"]
""")
    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": {"@playwright/mcp": "*"}})
    )
    before = snapshot(tmp_path)
    args = [
        "recommend",
        str(tmp_path),
        "--goal",
        "browser automation",
        "--tool",
        "serena",
        "--tool",
        "promptfoo",
        "--tool",
        "serena",
        "--model-preference",
        preference,
        "--json",
    ]
    assert cli.main(args) == 0
    first = capsys.readouterr().out
    assert cli.main(args) == 0
    assert capsys.readouterr().out == first
    payload = json.loads(first)
    rows = payload["recommendations"]
    assert [r["tool_id"] for r in rows] == ["serena", "promptfoo", "playwright-mcp", "headroom"]
    assert payload["model_preference_status"] == "unverified"
    browser = rows[2]
    assert browser["already_declared"] and {r["kind"] for r in browser["reasons"]} == {
        "goal",
        "dependency",
    }
    assert rows[3]["already_declared"]
    assert all(not row["eligibility"]["installable"] for row in rows)
    assert snapshot(tmp_path) == before and not (tmp_path / ".stackwinnow").exists()


def test_conflicting_explicit_choices_remain_visible_and_blocked(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_catalog", conflict_catalog)
    assert (
        cli.main(["recommend", str(tmp_path), "--tool", "serena", "--tool", "graphify", "--json"])
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert [r["tool_id"] for r in payload["recommendations"]] == ["serena", "graphify"]
    assert all(
        "selection-conflict" in {r["code"] for r in item["eligibility"]["reasons"]}
        for item in payload["recommendations"]
    )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("command", [["recommend"], ["workflow", "inspect"]])
def test_partial_discovery_preserves_valid_findings_and_returns_failure(tmp_path, capsys, command):
    (tmp_path / "pyproject.toml").write_text("""[project]
dependencies = ["headroom-ai"]
""")
    (tmp_path / "package.json").write_text('{not-json: "secret-do-not-print"}')
    before = snapshot(tmp_path)
    assert cli.main([*command, str(tmp_path), "--goal", "browser automation", "--json"]) == 1
    output = capsys.readouterr()
    assert not output.err and "secret-do-not-print" not in output.out
    payload = json.loads(output.out)
    rec = payload if command == ["recommend"] else payload["recommendations"]
    assert any(d["status"] == "failed" for d in rec["inspection"]["diagnostics"])
    assert {r["tool_id"] for r in rec["recommendations"]} == {"headroom", "playwright-mcp"}
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("goal", ["", "Build a calculator", "Avoid browser automation"])
def test_ambiguous_project_never_invents_selection(tmp_path, capsys, goal):
    args = ["recommend", str(tmp_path), "--json"] + (["--goal", goal] if goal else [])
    assert cli.main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["recommendations"] == []
    assert payload["unmatched_goals"] == ([goal] if goal else [])
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("tool", ["headroom", "graphify", "promptfoo", "playwright-mcp"])
def test_catalog_json_and_human_output_agree_on_registration_without_prerequisite_proof(
    tmp_path, capsys, tool
):
    args = ["catalog", "show", tool, "--platform", "macos", "--assistant", "codex"]
    assert cli.main([*args, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["tool"]["availability"] == "adapter_available"
    codes = {r["code"] for r in data["eligibility"]["reasons"]}
    assert "prerequisites-unverified" in codes
    assert codes.isdisjoint({"adapter-unregistered", "adapter-unavailable"})
    assert not data["eligibility"]["installable"]
    assert cli.main(args) == 0
    human = capsys.readouterr().out
    assert "Executable mode:" in human and "Mode requirements:" in human
    assert "Catalog gates: not established" in human
    assert "adapter-unregistered" not in human
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("action", ["plan", "status", "check"])
@pytest.mark.parametrize("tool", ["serena", "no-such-tool"])
def test_unsupported_execution_selection_fails_before_commands_or_state(
    tmp_path, capsys, monkeypatch, action, tool
):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid selections must not execute commands")

    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr("subprocess.Popen", forbidden)
    with pytest.raises(SystemExit) as failure:
        cli.main(["workflow", action, str(tmp_path), "--tool", tool, "--json"])
    assert failure.value.code == 2
    output = capsys.readouterr()
    assert not output.out and "workflow modes" in output.err and "Traceback" not in output.err
    assert list(tmp_path.iterdir()) == []


def test_recommended_tools_are_not_selected_when_reviewing_or_cancelling(project, tmp_path, capsys):
    before = snapshot(project)
    assert (
        cli.main(
            [
                "workflow",
                "plan",
                str(project),
                "--tool",
                "headroom",
                "--goal",
                "browser automation",
                "--json",
            ]
        )
        == 0
    )
    raw = capsys.readouterr().out
    payload = json.loads(raw)
    assert [s["tool_id"] for s in payload["request"]["selections"]] == ["headroom"]
    saved = tmp_path / "review.json"
    saved.write_text(raw)
    assert snapshot(project) == before and not (project / ".stackwinnow").exists()
    assert cli.main(["workflow", "apply", str(saved), "--dry-run", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["dry_run"] and not result["ready"]
    assert snapshot(project) == before and not (project / ".stackwinnow").exists()


@pytest.mark.parametrize(
    "command",
    [
        ["workflow", "modes"],
        ["workflow", "inspect"],
        ["workflow", "plan"],
        ["workflow", "apply"],
        ["workflow", "status"],
        ["workflow", "check"],
        ["profile", "export"],
        ["profile", "import"],
        ["remove", "plan"],
    ],
)
def test_installed_public_command_help_is_available_without_state(tmp_path, command):
    result = run_cli(tmp_path, *command, "--help")
    assert result.returncode == 0 and "usage: stackwinnow" in result.stdout and not result.stderr
    assert list(tmp_path.iterdir()) == []


def test_installed_discovery_browser_and_headroom_journey(tmp_path):
    (tmp_path / "pyproject.toml").write_text("""[project]
dependencies = ["Headroom_AI"]
""")
    before = snapshot(tmp_path)
    result = run_cli(
        tmp_path, "workflow", "inspect", str(tmp_path), "--goal", "browser automation", "--json"
    )
    assert result.returncode == 0 and not result.stderr
    payload = json.loads(result.stdout)
    recs = payload["recommendations"]["recommendations"]
    assert [r["tool_id"] for r in recs] == ["headroom", "playwright-mcp"]
    assert len(payload["executable_modes"]) == 23
    assert all(not r["eligibility"]["installable"] for r in recs)
    assert snapshot(tmp_path) == before

"""Exercise the installed command outside the source checkout."""

import json
import os
import subprocess
import sysconfig
from collections import Counter
from importlib.metadata import version
from pathlib import Path
from unittest.mock import Mock

import pytest
from conftest import subprocess_environment

from stackwinnow import cli
from stackwinnow.catalog import CatalogEntry, Eligibility, EligibilityContext, load_catalog


def run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    executable = Path(sysconfig.get_path("scripts")) / (
        "stackwinnow.exe" if os.name == "nt" else "stackwinnow"
    )
    assert executable.is_file(), "Install the package before running CLI tests."
    environment = subprocess_environment(Path.home())
    return subprocess.run(
        [str(executable), *args],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


@pytest.mark.parametrize("args", [(), ("--help",)])
def test_help_is_available_without_a_project(tmp_path: Path, args: tuple[str, ...]) -> None:
    result = run_cli(tmp_path, *args)

    assert result.returncode == 0
    assert "usage: stackwinnow" in result.stdout
    assert "--version" in result.stdout
    assert "catalog" in result.stdout
    assert "inspect" in result.stdout
    assert "recommend" in result.stdout
    assert "promptfoo" in result.stdout
    assert "check" in result.stdout
    assert "Promptfoo execution requires the shared runner" in " ".join(result.stdout.split())
    assert result.stderr == ""
    assert list(tmp_path.iterdir()) == []


def test_version_matches_installed_distribution(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "--version")

    assert result.returncode == 0
    assert result.stdout.strip() == f"stackwinnow {version('stackwinnow')}"
    assert result.stderr == ""
    assert list(tmp_path.iterdir()) == []


def test_check_installed_cli_reports_missing_setup_outside_checkout(tmp_path: Path) -> None:
    project = tmp_path / "selected project "
    project.mkdir()
    result = run_cli(tmp_path, "check", str(project), "--tool", "promptfoo", "--json")
    assert result.returncode == 1 and result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["project_root"] == str(project.resolve())
    assert payload["ready"] is False and payload["status"] == "failed"
    checks = {item["kind"]: item for item in payload["tools"][0]["checks"]}
    assert checks["installed"]["code"] == "installation-missing"
    assert checks["connected"]["status"] == "not_applicable"
    assert checks["functional"]["status"] == "blocked"
    assert list(project.iterdir()) == []


@pytest.mark.parametrize("args", [("install", "headroom"), ("--unknown-option",)])
def test_unimplemented_commands_and_unknown_options_fail(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    result = run_cli(tmp_path, *args)

    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr or "invalid choice" in result.stderr
    assert result.stdout == ""
    assert list(tmp_path.iterdir()) == []


def test_packaged_catalog_is_available_outside_checkout(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "catalog", "list", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["count"] == len(payload["tools"])
    assert {item["tool"]["tool_id"] for item in payload["tools"]} == {
        tool.tool_id for tool in load_catalog().tools
    }
    assert payload["schema_version"] == 1
    for item in payload["tools"]:
        assert "schema_version" not in item["tool"]
        assert CatalogEntry.model_validate(item["tool"]).schema_version == 1
    assert all(not item["eligibility"]["installable"] for item in payload["tools"])
    assert list(tmp_path.iterdir()) == []


def test_category_filter_and_show_json(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "catalog", "list", "--category", "evaluation", "--json")
    assert result.returncode == 0, result.stderr
    tools = json.loads(result.stdout)["tools"]
    assert {item["tool"]["tool_id"] for item in tools} == {
        "promptfoo",
        "deepeval",
        "ragas",
        "trulens",
        "inspect-ai",
    }
    shown = run_cli(
        tmp_path,
        "catalog",
        "show",
        "graphify",
        "--json",
        "--platform",
        "macos",
        "--assistant",
        "codex",
    )
    assert shown.returncode == 0, shown.stderr
    payload = json.loads(shown.stdout)
    assert payload["schema_version"] == 1
    assert "schema_version" not in payload["tool"]
    assert payload["tool"]["license"] == "Apache-2.0"
    assert {reason["code"] for reason in payload["eligibility"]["reasons"]} == {
        "adapter-unavailable",
        "prerequisites-unverified",
    }


def test_no_installable_tools_are_advertised(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "catalog", "list", "--installable", "--json")
    assert result.returncode == 0
    assert json.loads(result.stdout)["tools"] == []


@pytest.mark.parametrize(
    "args",
    [
        ("catalog", "show", "does-not-exist"),
        ("catalog", "list", "--category", "made-up"),
        ("catalog", "show", "graphify", "--assistant", "Invalid ID"),
        ("catalog", "list", "--inst", "--j"),
        ("catalog", "list", "--j"),
        ("catalog", "list", "--cat", "evaluation"),
        ("catalog", "show", "graphify", "--j"),
        ("catalog", "show", "graphify", "--plat", "macos"),
        ("catalog", "show", "graphify", "--assist", "codex"),
    ],
)
def test_catalog_input_errors_have_nonzero_exit_status(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    result = run_cli(tmp_path, *args)
    assert result.returncode == 2
    assert "error:" in result.stderr
    assert "Traceback" not in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_catalog_human_output_explains_limits(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "catalog", "show", "graphify")
    assert result.returncode == 0
    for text in (
        "Graphify",
        "Installation-ready: no",
        "Prerequisites:",
        "License scope:",
        "Sources:",
    ):
        assert text in result.stdout


@pytest.mark.parametrize("flags", [[], ["--json"]])
def test_unknown_tool_returns_failure_even_if_error_handler_returns(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], flags: list[str]
) -> None:
    handler = Mock(return_value=None)
    monkeypatch.setattr(cli.argparse.ArgumentParser, "error", handler)
    assert cli.main(["catalog", "show", "does-not-exist", *flags]) == 2
    handler.assert_called_once()
    assert "Unknown tool 'does-not-exist'" in handler.call_args.args[0]
    assert capsys.readouterr().out == ""


def test_installable_json_reuses_the_evaluation_used_for_selection(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: Counter[str] = Counter()

    def evaluate(tool: CatalogEntry, context: EligibilityContext) -> Eligibility:
        calls[tool.tool_id] += 1
        # Synthetic results exercise CLI selection/rendering, not real tool readiness.
        if tool.tool_id == "promptfoo":
            return Eligibility(installable=True, reasons=[])
        return Eligibility(
            installable=False,
            reasons=[{"code": "adapter-unavailable", "message": "Synthetic blocked result."}],
        )

    monkeypatch.setattr(cli, "evaluate_eligibility", evaluate)
    assert cli.main(["catalog", "list", "--category", "evaluation", "--installable", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["tools"][0]["tool"]["tool_id"] == "promptfoo"
    assert payload["tools"][0]["eligibility"] == {"installable": True, "reasons": []}
    assert calls == Counter(
        {"deepeval": 1, "inspect-ai": 1, "promptfoo": 1, "ragas": 1, "trulens": 1}
    )


def test_inspect_installed_cli_reports_intent_and_one_schema_version(tmp_path: Path) -> None:
    root = tmp_path / "project with spaces"
    root.mkdir()
    (root / "package.json").write_text('{"dependencies":{"react":"^18"}}')
    result = run_cli(
        tmp_path,
        "inspect",
        str(root),
        "--goal",
        "Evaluate answers",
        "--assistant",
        "codex",
        "--tool",
        "graphify",
        "--model-preference",
        "local",
        "--json",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["complete"]
    assert payload["profile"]["facts"]["node.dependencies"] == ["react"]
    assert payload["profile"]["goals"] == ["Evaluate answers"]
    assert payload["selected_tools"] == ["graphify"]
    assert payload["model_preference"] == "local"
    assert "schema_version" not in payload["profile"]
    assert all("schema_version" not in item for item in payload["diagnostics"])
    assert not (root / ".stackwinnow").exists()


def test_inspect_no_manifest_is_success_with_unknowns(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "inspect", ".")
    assert result.returncode == 0, result.stderr
    assert "Assistant: unknown" in result.stdout
    assert "No supported declarations" in result.stdout
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("extra", [[], ["--json"]])
def test_inspect_parse_failure_reports_partial_findings_and_exit_one(
    tmp_path: Path, extra: list[str]
) -> None:
    (tmp_path / "package.json").write_text('{"bad": synthetic-secret}')
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies=["requests"]')
    result = run_cli(tmp_path, "inspect", ".", *extra)
    assert result.returncode == 1
    assert "requests" in result.stdout
    assert "synthetic-secret" not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "args",
    [
        ("inspect", "does-not-exist"),
        ("inspect", ".", "--tool", "does-not-exist"),
        ("inspect", ".", "--goal", " "),
        ("inspect", ".", "--assistant", "Invalid ID"),
        ("inspect", ".", "--config", "../outside.json"),
        ("inspect", ".", "--model-preference", "invalid"),
        ("inspect", ".", "--j"),
    ],
)
def test_inspect_invalid_inputs_fail_without_writes(tmp_path: Path, args: tuple[str, ...]) -> None:
    result = run_cli(tmp_path, *args)
    assert result.returncode == 2
    assert "error:" in result.stderr
    assert "Traceback" not in result.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("options", [["--tool", "does-not-exist"], ["--goal", " "]])
def test_inspect_failure_does_not_render_when_exit_is_replaced(
    tmp_path, monkeypatch, capsys, options
):
    exit_stub = Mock()
    monkeypatch.setattr(cli.argparse.ArgumentParser, "exit", exit_stub)
    assert cli.main(["inspect", str(tmp_path), "--json", *options]) == 2
    exit_stub.assert_called_once()
    assert exit_stub.call_args.args[0] == 2
    assert capsys.readouterr().out == ""
    assert list(tmp_path.iterdir()) == []


def test_inspect_explicit_missing_configuration_exits_one(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "inspect", ".", "--config", "missing.json", "--json")
    assert result.returncode == 1
    assert not json.loads(result.stdout)["complete"]


def test_graphify_installed_cli_preview_is_explicitly_blocked_without_writes(tmp_path: Path):
    args = ("graphify", "plan", ".", "--platform", "macos", "--assistant", "codex")
    result = run_cli(tmp_path, *args, "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["phase"] == "preview-only" and not payload["ready_to_apply"]
    assert payload["artifact"]["distribution"] == "graphifyy"
    assert payload["artifact"]["version"] == "0.9.114"
    assert payload["blockers"]
    assert result.stdout.count('"schema_version"') == 1
    human = run_cli(tmp_path, *args)
    assert human.returncode == 0 and "Apply: unavailable (preview only)" in human.stdout
    assert "Shared verification" in human.stdout and "Codex" in human.stdout
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "args",
    [
        ("graphify", "plan", "."),
        ("graphify", "plan", ".", "--platform", "linux", "--assistant", "codex"),
        ("graphify", "plan", ".", "--platform", "macos", "--assistant", "cursor"),
        ("graphify", "plan", "missing", "--platform", "macos", "--assistant", "codex"),
        ("graphify", "apply", "plan.json"),
    ],
)
def test_graphify_cli_rejects_unsupported_or_incomplete_requests(tmp_path: Path, args):
    result = run_cli(tmp_path, *args)
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_graphify_cli_does_not_echo_corrupt_receipt_values(tmp_path: Path):
    (tmp_path / ".stackwinnow").mkdir()
    (tmp_path / ".stackwinnow/receipts.json").write_text('{"private":"synthetic-secret"}')
    result = run_cli(
        tmp_path, "graphify", "plan", ".", "--platform", "macos", "--assistant", "codex"
    )
    assert result.returncode == 2
    assert "synthetic-secret" not in result.stderr + result.stdout
    assert "Traceback" not in result.stderr


def test_graphify_execution_plan_installed_roundtrip_and_stale_source(tmp_path: Path):
    project = tmp_path / "source project"
    project.mkdir()
    source = project / "recursive.py"
    source.write_text("def recurse(): return recurse()\n")
    expectation = tmp_path / "expectation.json"
    expectation.write_text(
        json.dumps(
            {
                "caller_file": "recursive.py",
                "callee_file": "recursive.py",
                "caller_label": "recurse()",
                "callee_label": "recurse()",
            }
        )
    )
    args = ("graphify", "execution-plan", str(project), "--expectation", str(expectation))
    result = run_cli(tmp_path, *args, "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["phase"] == "execution-preparation"
    assert payload["ready_to_apply"] is False
    assert payload["target"] == "cpython311-macos14-arm64"
    assert len(payload["sources"]) == 1
    assert result.stdout.count('"schema_version"') == 1
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(result.stdout)
    validated = run_cli(tmp_path, "graphify", "validate-plan", str(plan_file), "--json")
    assert validated.returncode == 0, validated.stderr
    assert json.loads(validated.stdout) == payload
    human = run_cli(tmp_path, *args)
    assert human.returncode == 0 and "--install-only; full apply is pending" in human.stdout
    assert "No commands, downloads, or project writes" in human.stdout
    assert list(project.iterdir()) == [source]
    source.write_text("def recurse(): return None\n")
    stale = run_cli(tmp_path, "graphify", "validate-plan", str(plan_file))
    assert stale.returncode == 2 and "stale" in stale.stderr
    assert "Traceback" not in stale.stderr
    assert list(project.iterdir()) == [source]


@pytest.mark.parametrize("command", ["execution-plan", "validate-plan"])
def test_graphify_plan_cli_sanitizes_invalid_json(tmp_path: Path, command):
    path = tmp_path / "private.json"
    path.write_text('{"private":"synthetic-secret"}')
    args = (
        (str(tmp_path), "--expectation", str(path)) if command == "execution-plan" else (str(path),)
    )
    result = run_cli(tmp_path, "graphify", command, *args, "--json")
    assert result.returncode == 2
    assert "synthetic-secret" not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr


def test_recommend_installed_cli_explains_selection_and_project_evidence(tmp_path: Path) -> None:
    manifest = tmp_path / "package.json"
    manifest.write_text('{"devDependencies":{"promptfoo":"0.125.1"}}')
    before = manifest.read_bytes()
    result = run_cli(
        tmp_path,
        "recommend",
        ".",
        "--goal",
        "Evaluate answers",
        "--tool",
        "promptfoo",
        "--model-preference",
        "local",
        "--assistant",
        "codex",
        "--platform",
        "macos",
        "--json",
    )
    assert result.returncode == 0 and result.stderr == ""
    payload = json.loads(result.stdout)
    first = payload["recommendations"][0]
    assert first["tool_id"] == "promptfoo" and first["selected"] and first["already_declared"]
    assert {reason["kind"] for reason in first["reasons"]} == {"selection", "dependency", "goal"}
    goal_reason = next(reason for reason in first["reasons"] if reason["kind"] == "goal")
    assert goal_reason["matched_capabilities"] == ["prompt-evaluation"]
    assert not first["eligibility"]["installable"]
    assert payload["model_preference_status"] == "unverified"
    assert payload["inspection"]["model_preference"] == "local"
    assert payload["complete"] and payload["target_platform"] == "macos"
    assert result.stdout.count('"schema_version"') == 1
    assert manifest.read_bytes() == before and sorted(p.name for p in tmp_path.iterdir()) == [
        "package.json"
    ]


def test_recommend_human_output_and_unmatched_goal(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "recommend", ".", "--goal", "code navigation")
    assert result.returncode == 0
    for text in (
        "Graphify",
        "Serena",
        "Why:",
        "Setup: unavailable",
        "Alternatives",
        "Matched capabilities:",
        "code-relationships",
        "Relationships:\n  alternative: graphify / serena",
    ):
        assert text in result.stdout
    unmatched = run_cli(tmp_path, "recommend", ".", "--goal", "manage payroll", "--json")
    assert unmatched.returncode == 0
    payload = json.loads(unmatched.stdout)
    assert payload["recommendations"] == [] and payload["unmatched_goals"] == ["manage payroll"]
    assert list(tmp_path.iterdir()) == []


def test_recommend_human_output_omits_empty_relationship_section(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"dependencies":{"promptfoo":"*"}}')
    result = run_cli(tmp_path, "recommend", ".", "--goal", "Evaluate answers")
    assert result.returncode == 0
    assert "node.dependencies: promptfoo" in result.stdout
    assert "(Evaluate answers)" in result.stdout
    single = run_cli(tmp_path, "recommend", ".")
    assert single.returncode == 0
    assert "Relationships:" not in single.stdout


@pytest.mark.parametrize("selection", [[], ["--tool", "promptfoo"]])
def test_recommend_loads_one_catalog_for_inspection_and_matching(
    tmp_path, monkeypatch, capsys, selection
):
    loader = Mock(wraps=load_catalog)
    forbidden = Mock(side_effect=AssertionError("Reuse the catalog loaded by the CLI"))
    monkeypatch.setattr(cli, "load_catalog", loader)
    monkeypatch.setattr("stackwinnow.detect.load_catalog", forbidden)
    monkeypatch.setattr("stackwinnow.recommend.load_catalog", forbidden)
    assert (
        cli.main(["recommend", str(tmp_path), "--goal", "Evaluate answers", "--json", *selection])
        == 0
    )
    loader.assert_called_once_with()
    forbidden.assert_not_called()
    assert json.loads(capsys.readouterr().out)["recommendations"]


@pytest.mark.parametrize("goal", ["Don’t evaluate answers", "I won't evaluate answers"])
def test_recommend_installed_cli_does_not_invert_negated_goal(tmp_path: Path, goal: str):
    result = run_cli(tmp_path, "recommend", ".", "--goal", goal, "--json")
    assert result.returncode == 0 and result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["recommendations"] == [] and payload["unmatched_goals"] == [goal]


def test_recommend_incomplete_inspection_keeps_partial_json(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{invalid: "synthetic-secret"}')
    result = run_cli(tmp_path, "recommend", ".", "--goal", "Evaluate answers", "--json")
    assert result.returncode == 1 and result.stderr == ""
    payload = json.loads(result.stdout)
    assert not payload["complete"] and payload["recommendations"]
    assert any(item["status"] == "failed" for item in payload["inspection"]["diagnostics"])
    assert "synthetic-secret" not in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        ("missing-directory",),
        (".", "--tool", "unknown-tool"),
        (".", "--goal", " "),
        (".", "--assistant", "Invalid"),
        (".", "--platform", "unknown"),
        (".", "--config", "../outside.json"),
        (".", "--model-preference", "other"),
        (".", "--j"),
    ],
)
def test_recommend_rejects_invalid_arguments_without_writes(tmp_path: Path, args: tuple[str, ...]):
    result = run_cli(tmp_path, "recommend", *args)
    assert result.returncode == 2
    assert "error:" in result.stderr and "Traceback" not in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_inspect_deep_dependency_marker_returns_partial_json(tmp_path: Path) -> None:
    nested = "synthetic-secret; " + "(" * 1000 + 'python_version >= "3.11"' + ")" * 1000
    dependencies = json.dumps(["requests", nested, "pydantic"])
    (tmp_path / "pyproject.toml").write_text(f"[project]\ndependencies = {dependencies}")
    (tmp_path / "package.json").write_text('{"dependencies": {"react": "^18"}}')

    result = run_cli(tmp_path, "inspect", ".", "--json")

    assert result.returncode == 1
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert not payload["complete"]
    assert payload["profile"]["facts"]["python.dependencies"] == ["pydantic", "requests"]
    assert payload["profile"]["facts"]["node.dependencies"] == ["react"]
    assert any(
        item["status"] == "failed" and "project.dependencies" in item["message"]
        for item in payload["diagnostics"]
    )
    assert "synthetic-secret" not in result.stdout


@pytest.mark.parametrize("command", ["plan", "apply"])
def test_playwright_errors_return_two_when_parser_exit_is_replaced(
    tmp_path, monkeypatch, capsys, command
):
    exit_stub = Mock()
    monkeypatch.setattr(cli.argparse.ArgumentParser, "exit", exit_stub)

    def invalid(*args, **kwargs):
        raise ValueError("controlled invalid input")

    monkeypatch.setattr("stackwinnow.adapters.playwright_mcp.plan_playwright", invalid)
    monkeypatch.setattr("stackwinnow.adapters.playwright_mcp.load_playwright_plan", invalid)
    argv = ["playwright-mcp", command, str(tmp_path)]
    if command == "plan":
        argv.extend(["--assistant", "codex"])
    assert cli.main(argv) == 2
    exit_stub.assert_called_once_with(2, "error: Invalid Playwright plan or project state.\n")
    assert capsys.readouterr().out == ""

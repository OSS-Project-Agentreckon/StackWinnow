"""Exercise the installed command outside the source checkout."""

import json
import os
import subprocess
import sysconfig
from collections import Counter
from importlib.metadata import version
from pathlib import Path

import pytest
from conftest import subprocess_environment

from stackwinnow import cli
from stackwinnow.catalog import CatalogEntry, Eligibility, EligibilityContext


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
    assert "Installation is not available yet" in result.stdout
    assert result.stderr == ""
    assert list(tmp_path.iterdir()) == []


def test_version_matches_installed_distribution(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "--version")

    assert result.returncode == 0
    assert result.stdout.strip() == f"stackwinnow {version('stackwinnow')}"
    assert result.stderr == ""
    assert list(tmp_path.iterdir()) == []


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
    assert payload["count"] == 30
    assert payload["schema_version"] == 1
    for item in payload["tools"]:
        assert CatalogEntry.model_validate(item["tool"]).schema_version == 1
    assert len(payload["tools"]) == 30
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

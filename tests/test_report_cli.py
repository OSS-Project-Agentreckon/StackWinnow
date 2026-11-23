"""Exercise the installed `stackwinnow report` command outside the checkout."""

import json
import os
import subprocess
import sysconfig
from collections.abc import Callable
from pathlib import Path

from conftest import FixtureProject, subprocess_environment


def run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    executable = Path(sysconfig.get_path("scripts")) / (
        "stackwinnow.exe" if os.name == "nt" else "stackwinnow"
    )
    assert executable.is_file(), "Install the package before running CLI tests."
    return subprocess.run(
        [str(executable), *args],
        cwd=cwd,
        env=subprocess_environment(Path.home()),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def _node_project(
    root: Path, manifest: str = '{"devDependencies":{"promptfoo":"0.125.1"}}'
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text(manifest, encoding="utf-8")
    return root


def test_report_markdown_is_the_default_output(tmp_path: Path) -> None:
    project = _node_project(tmp_path / "proj")
    result = run_cli(project, "report", ".", "--goal", "Evaluate answers", "--tool", "promptfoo")
    assert result.returncode == 0 and result.stderr == ""
    for fragment in (
        "# StackWinnow report:",
        "## Recommended tools",
        "### promptfoo (`promptfoo`) — selected",
        "Read-only: no tools were installed, configured, or run.",
        "## Caveats",
    ):
        assert fragment in result.stdout
    assert list(project.iterdir()) == [project / "package.json"]


def test_report_json_payload_structure(tmp_path: Path) -> None:
    manifest = '{"devDependencies":{"promptfoo":"0.125.1"}}'
    project = _node_project(tmp_path / "proj", manifest)
    before = (project / "package.json").read_bytes()
    result = run_cli(
        project,
        "report",
        ".",
        "--goal",
        "Evaluate answers",
        "--tool",
        "promptfoo",
        "--platform",
        "macos",
        "--json",
    )
    assert result.returncode == 0 and result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert result.stdout.count('"schema_version"') == 1
    assert payload["recommendation"]["recommendations"][0]["tool_id"] == "promptfoo"
    assert payload["recommendation"]["complete"] is True
    assert payload["verification"] is None
    assert (project / "package.json").read_bytes() == before


def test_report_check_adds_passive_verification_without_writing(tmp_path: Path) -> None:
    project = _node_project(tmp_path / "proj")
    result = run_cli(project, "report", ".", "--tool", "promptfoo", "--check", "--json")
    # Nothing is installed, so the setup is not ready: exit 1 by convention.
    assert result.returncode == 1 and result.stderr == ""
    payload = json.loads(result.stdout)
    verification = payload["verification"]
    assert verification is not None
    kinds = {check["kind"] for check in verification["tools"][0]["checks"]}
    assert kinds == {"installed", "configured", "connected", "functional"}
    assert sorted(p.name for p in project.iterdir()) == ["package.json"]
    assert not (project / ".stackwinnow").exists()


def test_report_incomplete_inspection_exits_one(tmp_path: Path) -> None:
    project = _node_project(tmp_path / "proj")
    result = run_cli(project, "report", ".", "--config", "missing.json", "--json")
    assert result.returncode == 1
    assert json.loads(result.stdout)["recommendation"]["complete"] is False


def test_report_invalid_tool_exits_two(tmp_path: Path) -> None:
    project = _node_project(tmp_path / "proj")
    result = run_cli(project, "report", ".", "--tool", "not-a-real-tool")
    assert result.returncode == 2
    assert "error:" in result.stderr and "Traceback" not in result.stderr


def test_report_check_without_tool_exits_two(tmp_path: Path) -> None:
    project = _node_project(tmp_path / "proj")
    result = run_cli(project, "report", ".", "--check")
    assert result.returncode == 2
    assert "error:" in result.stderr and "Traceback" not in result.stderr


def test_report_rejects_abbreviated_flags(tmp_path: Path) -> None:
    project = _node_project(tmp_path / "proj")
    result = run_cli(project, "report", ".", "--js")
    assert result.returncode == 2 and "Traceback" not in result.stderr


def test_report_runs_in_a_path_with_spaces(
    project_factory: Callable[[], FixtureProject],
) -> None:
    project = project_factory().root  # fixture copies live under "fixture project N"
    result = run_cli(project, "report", ".", "--goal", "code navigation", "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["project_root"] == str(project)
    assert any(
        item["tool_id"] == "graphify" for item in payload["recommendation"]["recommendations"]
    )
    assert not (project / ".stackwinnow").exists()

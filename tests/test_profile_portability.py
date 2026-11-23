"""Export and import portable project profiles through the installed CLI and API."""

import json
import os
import subprocess
import sysconfig
from collections.abc import Callable
from pathlib import Path

from conftest import FixtureProject, subprocess_environment

from stackwinnow.detect import inspect_project
from stackwinnow.profiles import (
    PortableProfile,
    ProfileError,
    export_profile,
    import_profile,
    replan_profile,
)


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


def _node_project(root: Path, manifest: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text(manifest, encoding="utf-8")
    return root


# --- Export ---------------------------------------------------------------


def test_export_json_records_selections_preference_and_catalog_metadata(tmp_path: Path) -> None:
    project = _node_project(tmp_path / "proj", '{"devDependencies":{"promptfoo":"0.125.1"}}')
    result = run_cli(
        project,
        "profiles",
        "export",
        ".",
        "--goal",
        "Evaluate answers",
        "--tool",
        "promptfoo",
        "--model-preference",
        "local",
        "--platform",
        "macos",
        "--json",
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["goals"] == ["Evaluate answers"]
    assert payload["model_preference"] == "local"
    assert payload["target_platform"] == "macos"
    tool = payload["tools"][0]
    assert tool["tool_id"] == "promptfoo"
    assert tool["category"] == "evaluation"
    assert tool["license"] == "MIT"
    assert tool["version"] is None
    # A portable profile carries exactly one schema version, like other envelopes.
    assert result.stdout.count('"schema_version"') == 1


def test_export_human_output_lists_tools_and_the_exclusion_notice(tmp_path: Path) -> None:
    project = _node_project(tmp_path / "proj", '{"devDependencies":{"promptfoo":"0.125.1"}}')
    result = run_cli(project, "profiles", "export", ".", "--tool", "promptfoo")
    assert result.returncode == 0 and result.stderr == ""
    for text in (
        "Producer: StackWinnow",
        "promptfoo (promptfoo)",
        "Portable profiles exclude project paths, observed facts, and credentials.",
    ):
        assert text in result.stdout


def test_export_excludes_paths_facts_evidence_and_secrets(tmp_path: Path) -> None:
    manifest = (
        '{"dependencies":{"zz-secret-dep":"1.0.0"},"devDependencies":{"promptfoo":"0.125.1"}}'
    )
    project = _node_project(tmp_path / "private project ", manifest)
    config = project / "assistant.json"
    config.write_text('{"mcpServers":{"zz-secret-server":{"command":"synthetic-secret"}}}')
    result = run_cli(
        project,
        "profiles",
        "export",
        ".",
        "--tool",
        "promptfoo",
        "--config",
        "assistant.json",
        "--json",
    )
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    # Machine-specific state and secrets must never enter the portable artifact.
    assert str(project.resolve()) not in combined
    assert "zz-secret-dep" not in combined
    assert "zz-secret-server" not in combined
    assert "synthetic-secret" not in combined
    payload = json.loads(result.stdout)
    for excluded in ("project_root", "facts", "evidence", "diagnostics"):
        assert excluded not in payload


def test_export_round_trips_through_pydantic(tmp_path: Path) -> None:
    project = _node_project(tmp_path / "proj", '{"devDependencies":{"promptfoo":"0.125.1"}}')
    inspection = inspect_project(
        project, goals=["Evaluate answers"], selected_tools=["promptfoo"], model_preference="local"
    )
    profile = export_profile(inspection, platform=None)
    restored = PortableProfile.model_validate_json(profile.model_dump_json())
    assert restored == profile
    assert [entry.tool_id for entry in restored.tools] == ["promptfoo"]


def test_export_records_supplied_tested_version(tmp_path: Path) -> None:
    project = _node_project(tmp_path / "proj", "{}")
    inspection = inspect_project(project, selected_tools=["promptfoo"])
    profile = export_profile(inspection, tool_versions={"promptfoo": "0.125.1"})
    assert profile.tools[0].version == "0.125.1"


# --- Import / re-plan -----------------------------------------------------


def test_export_then_import_replans_in_a_second_project(
    project_factory: Callable[[], FixtureProject],
) -> None:
    source = project_factory().root
    _node_project(source, '{"devDependencies":{"promptfoo":"0.125.1"}}')
    target = project_factory().root

    export = run_cli(
        source,
        "profiles",
        "export",
        ".",
        "--goal",
        "Evaluate answers",
        "--tool",
        "promptfoo",
        "--json",
    )
    assert export.returncode == 0, export.stderr
    profile_file = source / "profile.json"
    profile_file.write_text(export.stdout, encoding="utf-8")

    replan = run_cli(target, "profiles", "import", str(profile_file), ".", "--json")
    assert replan.returncode == 0, replan.stderr
    payload = json.loads(replan.stdout)
    assert payload["inspection"]["selected_tools"] == ["promptfoo"]
    assert payload["inspection"]["profile"]["goals"] == ["Evaluate answers"]
    assert any(item["tool_id"] == "promptfoo" for item in payload["recommendations"])
    assert replan.stdout.count('"schema_version"') == 1


def test_import_human_output_renders_recommendations(tmp_path: Path) -> None:
    profile = PortableProfile(
        stackwinnow_version="0.1.0.dev0",
        goals=["code navigation"],
        tools=[],
    )
    profile_file = tmp_path / "profile.json"
    profile_file.write_text(profile.model_dump_json(), encoding="utf-8")
    project = _node_project(tmp_path / "proj", "{}")
    result = run_cli(project, "profiles", "import", str(profile_file), ".")
    assert result.returncode == 0 and result.stderr == ""
    assert "Recommendations:" in result.stdout


def test_import_applies_platform_override(tmp_path: Path) -> None:
    profile = PortableProfile(stackwinnow_version="0.1.0.dev0", target_platform="linux", tools=[])
    project = _node_project(tmp_path / "proj", "{}")
    result = replan_profile(profile, project, platform="macos")
    assert result.target_platform == "macos"


# --- Error handling -------------------------------------------------------


def test_import_missing_file_exits_two(tmp_path: Path) -> None:
    project = _node_project(tmp_path / "proj", "{}")
    result = run_cli(project, "profiles", "import", str(tmp_path / "absent.json"), ".")
    assert result.returncode == 2
    assert "error:" in result.stderr and "Traceback" not in result.stderr


def test_import_malformed_and_incompatible_profiles_exit_two(tmp_path: Path) -> None:
    project = _node_project(tmp_path / "proj", "{}")
    cases = {
        "not-json.json": "this is not json",
        "unknown-field.json": '{"schema_version":1,"stackwinnow_version":"x","surprise":true}',
        "wrong-version.json": '{"schema_version":2,"stackwinnow_version":"x"}',
        "unknown-tool.json": (
            '{"schema_version":1,"stackwinnow_version":"x",'
            '"tools":[{"tool_id":"not-a-real-tool","name":"X","category":"evaluation"}]}'
        ),
    }
    for name, body in cases.items():
        profile_file = tmp_path / name
        profile_file.write_text(body, encoding="utf-8")
        result = run_cli(project, "profiles", "import", str(profile_file), ".")
        assert result.returncode == 2, f"{name}: {result.stdout}"
        assert "error:" in result.stderr and "Traceback" not in result.stderr
        assert "proj" not in result.stderr  # fixed messages must not echo input paths


def test_export_unknown_tool_exits_two(tmp_path: Path) -> None:
    project = _node_project(tmp_path / "proj", "{}")
    result = run_cli(project, "profiles", "export", ".", "--tool", "not-a-real-tool")
    assert result.returncode == 2
    assert "error:" in result.stderr and "Traceback" not in result.stderr


def test_export_abbreviated_flags_are_rejected(tmp_path: Path) -> None:
    project = _node_project(tmp_path / "proj", "{}")
    result = run_cli(project, "profiles", "export", ".", "--js")
    assert result.returncode == 2
    assert "Traceback" not in result.stderr


def test_profiles_requires_a_subcommand(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "profiles")
    assert result.returncode == 2
    assert "Traceback" not in result.stderr


# --- Direct API error surface --------------------------------------------


def test_import_profile_rejects_malformed_json() -> None:
    try:
        import_profile("{ not valid")
    except ProfileError:
        return
    raise AssertionError("import_profile should raise ProfileError for malformed input")


def test_export_profile_rejects_tool_absent_from_catalog(tmp_path: Path) -> None:
    project = _node_project(tmp_path / "proj", "{}")
    inspection = inspect_project(project).model_copy(update={"selected_tools": ["not-a-real-tool"]})
    try:
        export_profile(inspection)
    except ProfileError:
        return
    raise AssertionError("export_profile should raise ProfileError for an uncatalogued tool")

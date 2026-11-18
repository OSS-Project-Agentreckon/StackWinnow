"""Project inspection reports declarations without running project code."""

import errno
import json
import os
import subprocess
from pathlib import Path

import pytest
from conftest import FixtureProject
from pydantic import ValidationError

from stackwinnow import detect
from stackwinnow.detect import InspectionError, InspectionResult, inspect_project

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Bounded file reader uses POSIX APIs")


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_python_declarations_and_explicit_intent_are_separate(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("""
[project]
name = "sample"
requires-python = ">=3.11,<4"
dependencies = ["LangChain_Core>=0.2", "Requests[security]; python_version >= '3.11'"]
[project.optional-dependencies]
test = ["pytest>=8"]
""")
    result = inspect_project(
        tmp_path,
        goals=["Reduce model calls", "Evaluate answers"],
        assistant="codex",
        selected_tools=["graphify", "promptfoo", "graphify"],
        model_preference="local",
    )
    assert result.complete
    assert result.profile.facts == {
        "manifests": ["pyproject.toml"],
        "ecosystems": ["python"],
        "python.dependencies": ["langchain-core", "requests"],
        "python.optional_dependencies.test": ["pytest"],
        "python.requires": ["<4,>=3.11"],
    }
    assert result.profile.goals == ["Reduce model calls", "Evaluate answers"]
    assert result.profile.assistant == "codex"
    assert result.profile.operating_system is None
    assert result.selected_tools == ["graphify", "promptfoo"]
    assert result.model_preference == "local"
    assert InspectionResult.model_validate_json(result.model_dump_json()) == result
    assert all(item.source == "pyproject.toml" for item in result.profile.evidence)
    assert any("project.dependencies" in item.detail for item in result.profile.evidence)


def test_node_declarations_distinguish_dependency_groups(tmp_path: Path) -> None:
    write_json(
        tmp_path / "package.json",
        {
            "dependencies": {"@scope/client": "^2.0", "react": "^18"},
            "devDependencies": {"typescript": "^5"},
            "optionalDependencies": {},
            "peerDependencies": {"react": ">=18"},
            "engines": {"node": ">=22.22.0"},
        },
    )
    result = inspect_project(tmp_path)
    assert result.complete
    assert result.profile.facts == {
        "manifests": ["package.json"],
        "ecosystems": ["node"],
        "node.dependencies": ["@scope/client", "react"],
        "node.devDependencies": ["typescript"],
        "node.optionalDependencies": [],
        "node.peerDependencies": ["react"],
        "node.requires": [">=22.22.0"],
    }
    assert result.profile.goals == []
    assert result.profile.assistant is None
    assert result.model_preference is None


def test_mixed_project_reuses_the_existing_fixture(fixture_project: FixtureProject) -> None:
    write_json(fixture_project.root / "package.json", {"dependencies": {"react": "*"}})
    result = inspect_project(fixture_project.root, config_path=fixture_project.settings.name)
    assert result.complete
    assert result.profile.facts["ecosystems"] == ["node", "python"]
    assert result.profile.facts["config.mcp_servers"] == ["existing-fixture-server"]
    assert "keep-existing-theme" not in result.model_dump_json()


def test_empty_project_remains_unknown(tmp_path: Path) -> None:
    result = inspect_project(tmp_path)
    assert result.complete
    assert result.profile.facts == {}
    assert result.profile.evidence == []
    assert all(item.status == "skipped" for item in result.diagnostics)


@pytest.mark.parametrize("text", ['[project]\nname="app"', '[tool.poetry]\nname="app"'])
def test_missing_dependency_fields_are_not_reported_as_empty(tmp_path: Path, text: str) -> None:
    (tmp_path / "pyproject.toml").write_text(text)
    result = inspect_project(tmp_path)
    assert result.complete
    assert "python.dependencies" not in result.profile.facts


def test_dynamic_and_workspace_metadata_are_not_executed_or_recursed(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\ndynamic=["dependencies"]')
    write_json(tmp_path / "package.json", {"workspaces": ["child"]})
    (tmp_path / "child").mkdir()
    write_json(tmp_path / "child/package.json", {"dependencies": {"hidden": "*"}})
    result = inspect_project(tmp_path)
    assert result.complete
    assert "python.dependencies" not in result.profile.facts
    assert "node.dependencies" not in result.profile.facts
    assert "Dynamic" in result.model_dump_json()
    assert "Workspace" in result.model_dump_json()
    assert "hidden" not in result.model_dump_json()


def test_conflicting_static_and_dynamic_metadata_remains_unknown(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies=["requests"]\ndynamic=["dependencies"]'
    )
    result = inspect_project(tmp_path)
    assert not result.complete
    assert "python.dependencies" not in result.profile.facts


def test_invalid_values_do_not_become_explicitly_empty_declarations(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\ndependencies=[1]")
    write_json(tmp_path / "package.json", {"dependencies": {"bad": []}})
    write_json(tmp_path / "settings.json", {"mcpServers": {"bad": "invalid"}})
    result = inspect_project(tmp_path, config_path="settings.json")
    assert not result.complete
    for key in ("python.dependencies", "node.dependencies", "config.mcp_servers"):
        assert key not in result.profile.facts


def test_changed_input_is_reported_instead_of_using_unstable_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "package.json"
    target.write_text("{}")
    original_fdopen = detect.os.fdopen

    def changed(descriptor, *args, **kwargs):
        target.write_text('{"changed":true}')
        return original_fdopen(descriptor, *args, **kwargs)

    monkeypatch.setattr(detect.os, "fdopen", changed)
    result = inspect_project(tmp_path)
    assert not result.complete
    assert "changed while being read" in result.model_dump_json()
    assert "node.dependencies" not in result.profile.facts


@pytest.mark.parametrize(
    "raw",
    [b"{", b"[]", b"null", b"\xff", b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}', b'{"x":1,}'],
)
def test_invalid_json_reports_failure_but_preserves_other_facts(tmp_path: Path, raw: bytes) -> None:
    (tmp_path / "package.json").write_bytes(raw)
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies=["pytest"]')
    result = inspect_project(tmp_path)
    assert not result.complete
    assert result.profile.facts["python.dependencies"] == ["pytest"]
    assert result.profile.facts["ecosystems"] == ["python"]
    assert any(
        item.status == "failed" and "package.json" in item.message for item in result.diagnostics
    )
    assert (tmp_path / "package.json").read_bytes() == raw


def test_malformed_toml_does_not_leak_source_values(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('synthetic-secret="unterminated')
    result = inspect_project(tmp_path)
    assert not result.complete
    assert "synthetic-secret" not in result.model_dump_json()


@pytest.mark.parametrize(
    "document",
    [
        {"dependencies": []},
        {"dependencies": {"good": "*", "bad": {"secret": "value"}}},
        {"engines": []},
        {"engines": {"node": "https://synthetic-secret.example"}},
    ],
)
def test_invalid_node_field_shapes_are_diagnostic(tmp_path: Path, document: dict) -> None:
    write_json(tmp_path / "package.json", document)
    result = inspect_project(tmp_path)
    assert not result.complete
    assert "synthetic-secret" not in result.model_dump_json()


@pytest.mark.parametrize(
    "metadata",
    [
        'dependencies="synthetic-secret"',
        'dependencies=["good", "bad !!! synthetic-secret"]',
        "optional-dependencies=[]",
        'requires-python="synthetic-secret"',
        "dynamic=[1]",
    ],
)
def test_invalid_python_field_shapes_are_diagnostic(tmp_path: Path, metadata: str) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\n" + metadata)
    result = inspect_project(tmp_path)
    assert not result.complete
    assert "synthetic-secret" not in result.model_dump_json()


def test_only_names_are_reported_from_dependency_urls_and_config_values(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("""
[project]
dependencies = ["private-package @ https://user:synthetic-secret@example.invalid/pkg.whl"]
""")
    write_json(
        tmp_path / "package.json",
        {
            "dependencies": {"private-js": "https://user:synthetic-secret@example.invalid/pkg.tgz"},
            "scripts": {"postinstall": "synthetic-secret"},
        },
    )
    write_json(
        tmp_path / "settings.json",
        {
            "mcpServers": {
                "example": {"command": "synthetic-secret", "env": {"KEY": "synthetic-secret"}}
            },
            "token": "synthetic-secret",
        },
    )
    result = inspect_project(tmp_path, config_path="settings.json")
    assert result.complete
    assert result.profile.facts["python.dependencies"] == ["private-package"]
    assert result.profile.facts["node.dependencies"] == ["private-js"]
    assert result.profile.facts["config.mcp_servers"] == ["example"]
    assert "synthetic-secret" not in result.model_dump_json()
    assert "example.invalid" not in result.model_dump_json()


@pytest.mark.parametrize(
    "document",
    [{}, {"mcpServers": {}}, {"mcpServers": []}, {"mcpServers": {"invalid": "not an object"}}],
)
def test_config_unknown_empty_and_invalid_are_distinct(tmp_path: Path, document: dict) -> None:
    write_json(tmp_path / "settings.json", document)
    result = inspect_project(tmp_path, config_path="settings.json")
    if document == {}:
        assert "config.mcp_servers" not in result.profile.facts
        assert result.complete
    elif document == {"mcpServers": {}}:
        assert result.profile.facts["config.mcp_servers"] == []
        assert result.complete
    else:
        assert not result.complete


def test_selected_missing_config_is_an_error(tmp_path: Path) -> None:
    assert not inspect_project(tmp_path, config_path="missing.json").complete


@pytest.mark.parametrize("name", ["   ", " server", "server "])
@pytest.mark.parametrize("keep_valid", [False, True])
def test_padded_server_names_are_rejected_without_corrupting_roundtrip(
    tmp_path: Path, name: str, keep_valid: bool
) -> None:
    servers = {name: {}}
    if keep_valid:
        servers["server"] = {}
    write_json(tmp_path / "settings.json", {"mcpServers": servers})
    result = inspect_project(tmp_path, config_path="settings.json")
    assert not result.complete
    if keep_valid:
        assert result.profile.facts["config.mcp_servers"] == ["server"]
    else:
        assert "config.mcp_servers" not in result.profile.facts
    assert InspectionResult.model_validate_json(result.model_dump_json()) == result


def test_project_and_evidence_paths_keep_significant_spaces(tmp_path: Path) -> None:
    root = tmp_path / "project "
    root.mkdir()
    source = " settings.json"
    write_json(root / source, {"mcpServers": {"server": {}}})
    result = inspect_project(root, config_path=source)
    assert result.complete
    assert result.profile.project_root == str(root.resolve())
    assert Path(result.profile.project_root).is_dir()
    assert result.profile.evidence[0].source == source
    assert InspectionResult.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize(
    "constraint", [">=3.14.0rc1", ">=3.14.0.dev1", "!=3.11.*,>=3.10", "===3.11"]
)
def test_python_version_constraints_accept_pep440_versions(tmp_path: Path, constraint: str) -> None:
    (tmp_path / "pyproject.toml").write_text(f'[project]\nrequires-python = "{constraint}"')
    result = inspect_project(tmp_path)
    assert result.complete
    assert result.profile.facts["python.requires"] == [constraint]
    assert InspectionResult.model_validate_json(result.model_dump_json()) == result


def test_arbitrary_python_equality_does_not_expose_non_version_values(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nrequires-python = "===synthetic-secret"')
    result = inspect_project(tmp_path)
    assert not result.complete
    assert "python.requires" not in result.profile.facts
    assert "synthetic-secret" not in result.model_dump_json()


@pytest.mark.parametrize(
    "path",
    [
        "../outside.json",
        "/outside.json",
        "./settings.json",
        ".env",
        "nested/../../outside.json",
        "nested\\settings.json",
    ],
)
def test_invalid_config_paths_are_rejected(tmp_path: Path, path: str) -> None:
    with pytest.raises(InspectionError, match="project-relative"):
        inspect_project(tmp_path, config_path=path)


@pytest.mark.parametrize("kind", ["symlink", "dangling", "hardlink", "directory", "fifo", "large"])
def test_unsupported_manifest_files_are_blocked(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "project"
    root.mkdir()
    target = root / "package.json"
    outside = tmp_path / "outside.json"
    outside.write_text('{"dependencies":{"outside-secret":"*"}}')
    if kind == "symlink":
        target.symlink_to(outside)
    elif kind == "dangling":
        target.symlink_to(tmp_path / "missing.json")
    elif kind == "hardlink":
        os.link(outside, target)
    elif kind == "directory":
        target.mkdir()
    elif kind == "fifo":
        os.mkfifo(target)
    else:
        target.write_bytes(b" " * (detect.MAX_MANIFEST_BYTES + 1))
    result = inspect_project(root)
    assert not result.complete
    assert "outside-secret" not in result.model_dump_json()


def test_config_parent_symlink_is_not_followed(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    write_json(outside / "settings.json", {"mcpServers": {"outside-secret": {}}})
    (root / "linked").symlink_to(outside, target_is_directory=True)
    result = inspect_project(root, config_path="linked/settings.json")
    assert not result.complete
    assert "outside-secret" not in result.model_dump_json()


def test_unreadable_input_has_sanitized_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_open = detect.os.open

    def denied(path, *args, **kwargs):
        if path == "package.json":
            raise PermissionError(errno.EACCES, "synthetic-secret")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(detect.os, "open", denied)
    result = inspect_project(tmp_path)
    assert not result.complete
    assert "synthetic-secret" not in result.model_dump_json()
    assert "permissions" in result.model_dump_json()


def test_invalid_project_and_explicit_inputs(tmp_path: Path) -> None:
    with pytest.raises(InspectionError):
        inspect_project(tmp_path / "missing")
    target = tmp_path / "file"
    target.touch()
    with pytest.raises(InspectionError):
        inspect_project(target)
    with pytest.raises(InspectionError, match="Unknown tool"):
        inspect_project(tmp_path, selected_tools=["unknown-tool"])
    with pytest.raises(ValidationError):
        inspect_project(tmp_path, goals=[" "])


def test_inspection_never_executes_scripts_or_changes_project(
    fixture_project: FixtureProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = fixture_project.root
    write_json(root / "package.json", {"scripts": {"postinstall": "touch unexpected-file"}})
    (root / ".env").write_text("synthetic-secret")
    before = {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }

    def forbidden(*args, **kwargs):
        raise AssertionError("Inspection must not execute tools or discover a home directory")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(Path, "home", forbidden)
    result = inspect_project(root, config_path=fixture_project.settings.name)
    after = {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }
    assert result.complete
    assert before == after
    assert "synthetic-secret" not in result.model_dump_json()

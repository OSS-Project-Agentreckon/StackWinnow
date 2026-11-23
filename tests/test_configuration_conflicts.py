"""Read-only reconciliation of an owned ConfigPatch against the current file.

No assistant or tool is executed; projects are copied fixtures.
"""

import json
import os
from pathlib import Path

import pytest
from conftest import FixtureProject

from stackwinnow.configure import (
    apply_json_edits,
    plan_json_edits,
    reconcile_config_patch,
)
from stackwinnow.contracts import (
    ConfigPatch,
    ConfigReconcileReport,
    ConflictKind,
    FileState,
    JsonConfigEdit,
    KeyConflict,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="reconcile reads via POSIX file APIs")


def _apply_server(project: FixtureProject) -> ConfigPatch:
    edit = JsonConfigEdit(
        key_path=("mcpServers", "fixture-tool"),
        value={"command": "fixture-only-do-not-execute"},
    )
    patch = plan_json_edits(
        project.root, project.settings.name, tool_id="fixture-tool", edits=[edit]
    )
    assert apply_json_edits(patch).result.status == "succeeded"
    return patch


# --- Task 1: contracts -------------------------------------------------------


def test_report_safe_to_revert_only_when_readable_and_all_clean() -> None:
    clean = ConfigReconcileReport(
        project_root="/tmp/x",
        relative_path="a.json",
        tool_id="fixture-tool",
        file_state=FileState.READABLE,
        keys=(KeyConflict(key_path=("mcpServers", "fixture-tool"), kind=ConflictKind.CLEAN),),
    )
    assert clean.safe_to_revert is True
    assert clean.requires_attention == ()


def test_report_not_safe_when_a_key_conflicts() -> None:
    report = ConfigReconcileReport(
        project_root="/tmp/x",
        relative_path="a.json",
        tool_id="fixture-tool",
        file_state=FileState.READABLE,
        keys=(
            KeyConflict(key_path=("mcpServers", "fixture-tool"), kind=ConflictKind.USER_MODIFIED),
        ),
    )
    assert report.safe_to_revert is False
    assert len(report.requires_attention) == 1


def test_report_not_safe_when_file_unreadable_even_with_no_keys() -> None:
    report = ConfigReconcileReport(
        project_root="/tmp/x",
        relative_path="a.json",
        tool_id="fixture-tool",
        file_state=FileState.UNREADABLE,
    )
    assert report.safe_to_revert is False


def test_report_round_trips_through_json() -> None:
    report = ConfigReconcileReport(
        project_root="/tmp/x",
        relative_path="a.json",
        tool_id="fixture-tool",
        file_state=FileState.STALE,
    )
    assert ConfigReconcileReport.model_validate_json(report.model_dump_json()) == report


# --- Task 2: per-key classification against written values -------------------


def _rewrite(project: FixtureProject, data: dict) -> None:
    project.settings.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def test_unchanged_owned_value_is_clean(fixture_project: FixtureProject) -> None:
    patch = _apply_server(fixture_project)
    report = reconcile_config_patch(patch)
    assert report.file_state is FileState.READABLE
    assert [k.kind for k in report.keys] == [ConflictKind.CLEAN]
    assert report.safe_to_revert is True


def test_user_modified_owned_value_is_reported_on_exact_key(
    fixture_project: FixtureProject,
) -> None:
    patch = _apply_server(fixture_project)
    data = json.loads(fixture_project.settings.read_text())
    data["mcpServers"]["fixture-tool"] = {"command": "user-changed-it"}
    _rewrite(fixture_project, data)
    report = reconcile_config_patch(patch)
    assert report.file_state is FileState.STALE
    conflict = report.requires_attention
    assert len(conflict) == 1
    assert conflict[0].key_path == ("mcpServers", "fixture-tool")
    assert conflict[0].kind is ConflictKind.USER_MODIFIED


def test_user_removed_owned_key_is_user_removed(fixture_project: FixtureProject) -> None:
    patch = _apply_server(fixture_project)
    data = json.loads(fixture_project.settings.read_text())
    del data["mcpServers"]["fixture-tool"]
    _rewrite(fixture_project, data)
    report = reconcile_config_patch(patch)
    assert [k.kind for k in report.keys] == [ConflictKind.USER_REMOVED]


def test_present_null_is_modified_not_removed(fixture_project: FixtureProject) -> None:
    patch = _apply_server(fixture_project)
    data = json.loads(fixture_project.settings.read_text())
    data["mcpServers"]["fixture-tool"] = None
    _rewrite(fixture_project, data)
    report = reconcile_config_patch(patch)
    assert [k.kind for k in report.keys] == [ConflictKind.USER_MODIFIED]


def test_unrelated_sibling_key_does_not_appear(fixture_project: FixtureProject) -> None:
    patch = _apply_server(fixture_project)
    report = reconcile_config_patch(patch)
    assert all(k.key_path == ("mcpServers", "fixture-tool") for k in report.keys)


def test_diagnostics_never_contain_config_values(fixture_project: FixtureProject) -> None:
    patch = _apply_server(fixture_project)
    data = json.loads(fixture_project.settings.read_text())
    data["mcpServers"]["fixture-tool"] = {"command": "SENSITIVE-SECRET-VALUE"}
    _rewrite(fixture_project, data)
    report = reconcile_config_patch(patch)
    assert "SENSITIVE-SECRET-VALUE" not in report.model_dump_json()


# --- Task 3: file-state safety -----------------------------------------------


def test_missing_file_is_reported_not_raised(fixture_project: FixtureProject) -> None:
    patch = _apply_server(fixture_project)
    fixture_project.settings.unlink()
    report = reconcile_config_patch(patch)
    assert report.file_state is FileState.MISSING


def test_malformed_file_is_unreadable_and_does_not_raise(
    fixture_project: FixtureProject,
) -> None:
    patch = _apply_server(fixture_project)
    fixture_project.settings.write_text("{ this is : not json")
    report = reconcile_config_patch(patch)
    assert report.file_state is FileState.UNREADABLE


def test_toml_format_patch_is_unsupported_without_reading(
    fixture_project: FixtureProject,
) -> None:
    patch = _apply_server(fixture_project)
    toml_patch = patch.model_copy(update={"format": "toml"})
    report = reconcile_config_patch(toml_patch)
    assert report.file_state is FileState.UNSUPPORTED
    assert report.keys == ()


def test_codex_toml_reconciliation_preserves_unrelated_comments(tmp_path):
    from stackwinnow.configure.codex import apply_codex_server, plan_codex_server

    (tmp_path / ".codex").mkdir()
    path = tmp_path / ".codex/config.toml"
    path.write_text('# user comment\nmodel = "user-model"\n')
    patch = plan_codex_server(tmp_path, {"command": "managed-server", "args": []})
    apply_codex_server(patch)
    path.write_text(path.read_text() + "# new user comment\n")
    before = path.read_bytes()

    report = reconcile_config_patch(patch)

    assert report.file_state is FileState.STALE
    assert report.keys[0].kind is ConflictKind.CLEAN
    assert path.read_bytes() == before


def test_codex_toml_date_added_to_owned_table_is_user_modified(tmp_path):
    from stackwinnow.configure.codex import apply_codex_server, plan_codex_server

    (tmp_path / ".codex").mkdir()
    path = tmp_path / ".codex/config.toml"
    patch = plan_codex_server(tmp_path, {"command": "managed-server", "args": []})
    apply_codex_server(patch)
    path.write_text(path.read_text() + "last_used = 2026-11-23\n")

    report = reconcile_config_patch(patch)

    assert report.keys[0].kind is ConflictKind.USER_MODIFIED
    assert "2026" not in report.model_dump_json()


def test_symlinked_config_is_refused_as_unreadable(
    fixture_project: FixtureProject, tmp_path: Path
) -> None:
    patch = _apply_server(fixture_project)
    real = fixture_project.settings.read_bytes()
    fixture_project.settings.unlink()
    target = tmp_path / "elsewhere.json"
    target.write_bytes(real)
    fixture_project.settings.symlink_to(target)
    report = reconcile_config_patch(patch)
    assert report.file_state is FileState.UNREADABLE


def test_relocated_project_root_is_reported_not_crashed(
    fixture_project: FixtureProject,
) -> None:
    patch = _apply_server(fixture_project)
    moved = patch.model_copy(update={"project_root": patch.project_root + "-gone"})
    report = reconcile_config_patch(moved)
    assert report.file_state in (FileState.MISSING, FileState.UNREADABLE)


# --- Task 4: foreign registration detection via intended edits ---------------


def test_preexisting_registration_is_foreign_when_intended_but_not_written(
    fixture_project: FixtureProject,
) -> None:
    # The fixture already contains mcpServers.existing-fixture-server; we never wrote it.
    patch = _apply_server(fixture_project)  # owns only ("mcpServers", "fixture-tool")
    intended = [
        JsonConfigEdit(key_path=("mcpServers", "fixture-tool"), value={"command": "x"}),
        JsonConfigEdit(key_path=("mcpServers", "existing-fixture-server"), value={"command": "y"}),
    ]
    report = reconcile_config_patch(patch, intended_edits=intended)
    foreign = [k for k in report.keys if k.kind is ConflictKind.FOREIGN_PRESENT]
    assert len(foreign) == 1
    assert foreign[0].key_path == ("mcpServers", "existing-fixture-server")


def test_no_intended_edits_never_reports_foreign(fixture_project: FixtureProject) -> None:
    patch = _apply_server(fixture_project)
    report = reconcile_config_patch(patch)
    assert all(k.kind is not ConflictKind.FOREIGN_PRESENT for k in report.keys)


def test_intended_key_whose_parent_is_nonobject_is_foreign(
    fixture_project: FixtureProject,
) -> None:
    patch = _apply_server(fixture_project)
    intended = [JsonConfigEdit(key_path=("theme", "nested"), value="z")]  # theme is a string
    report = reconcile_config_patch(patch, intended_edits=intended)
    assert any(
        k.key_path == ("theme", "nested") and k.kind is ConflictKind.FOREIGN_PRESENT
        for k in report.keys
    )

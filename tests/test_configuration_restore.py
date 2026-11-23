"""Owned cleanup preserves user data and exposes live runtime dependencies."""

import json
import os
import tomllib

import pytest

from stackwinnow.configure import (
    apply_config_restore,
    apply_json_edits,
    plan_config_restore,
    plan_json_edits,
    reconcile_config_patch,
    referenced_runtime_paths,
)
from stackwinnow.configure.codex import apply_codex_server, plan_codex_server
from stackwinnow.contracts import ConflictKind, FileState, JsonConfigEdit
from stackwinnow.state.lock import project_lock


def json_ownership(root):
    path = root / "settings.json"
    path.write_text('{"replace": null, "unrelated": {"keep": true}}')
    patch = plan_json_edits(
        root,
        "settings.json",
        tool_id="test-tool",
        edits=[
            JsonConfigEdit(key_path=("replace",), value="managed", replace_existing=True),
            JsonConfigEdit(key_path=("created", "child"), value="managed"),
        ],
    )
    assert apply_json_edits(patch).ownership == patch
    return patch, path


def codex_ownership(root):
    (root / ".codex").mkdir()
    path = root / ".codex/config.toml"
    original = b'# user comment\nmodel = "user-model"\n'
    path.write_bytes(original)
    patch = plan_codex_server(
        root, {"command": str(root / ".stackwinnow/envs/tool/bin/server"), "args": []}
    )
    assert apply_codex_server(patch).ownership == patch
    return patch, path, original


def test_json_restores_replaced_null_and_prunes_only_created_objects(tmp_path):
    patch, path = json_ownership(tmp_path)
    path.chmod(0o640)
    plan = plan_config_restore(patch)
    before = path.read_bytes()
    assert plan.restore_keys == (("replace",), ("created", "child"))
    assert path.read_bytes() == before
    with project_lock(tmp_path):
        result = apply_config_restore(plan)
    assert result.result.status == "succeeded" and result.published
    assert result.plan.ownership == patch
    assert json.loads(path.read_text()) == {"replace": None, "unrelated": {"keep": True}}
    assert path.stat().st_mode & 0o777 == 0o640
    assert not list(tmp_path.glob(".stackwinnow-restore-*"))


def test_json_preserves_modified_removed_and_foreign_keys(tmp_path):
    patch, path = json_ownership(tmp_path)
    data = json.loads(path.read_text())
    data["replace"] = "user edit"
    data["created"]["other"] = "user value"
    data["foreign"] = "keep"
    path.write_text(json.dumps(data))
    plan = plan_config_restore(patch)
    assert plan.restore_keys == (("created", "child"),)
    assert plan.retained_keys[0].kind == ConflictKind.USER_MODIFIED
    result = apply_config_restore(plan)
    assert result.result.status == "succeeded"
    assert json.loads(path.read_text()) == {
        "replace": "user edit",
        "created": {"other": "user value"},
        "foreign": "keep",
        "unrelated": {"keep": True},
    }
    again = apply_config_restore(plan_config_restore(patch))
    assert again.result.status == "skipped"
    assert not again.published


def test_missing_file_stays_missing_and_releases_owned_keys(tmp_path):
    patch, path = json_ownership(tmp_path)
    path.unlink()
    result = apply_config_restore(plan_config_restore(patch))
    assert result.result.status == "skipped"
    assert result.released_keys == tuple(edit.key_path for edit in patch.edits)
    assert not path.exists()


@pytest.mark.parametrize("change", ["content", "mode", "symlink", "parent"])
def test_stale_restore_plan_never_writes(tmp_path, change):
    patch, path, _ = codex_ownership(tmp_path)
    plan = plan_config_restore(patch)
    if change == "content":
        path.write_bytes(path.read_bytes() + b"# user edit\n")
    elif change == "mode":
        path.chmod(0o400)
    elif change == "symlink":
        target = tmp_path / "outside.toml"
        path.rename(target)
        path.symlink_to(target)
    else:
        moved = tmp_path / "moved"
        path.parent.rename(moved)
        path.parent.symlink_to(moved, target_is_directory=True)
    before = path.read_bytes()
    result = apply_config_restore(plan)
    assert result.result.status == "blocked" and not result.published
    assert result.plan.ownership == patch
    assert path.read_bytes() == before


def test_codex_reconciliation_and_restore_preserve_unrelated_bytes(tmp_path):
    patch, path, original = codex_ownership(tmp_path)
    suffix = b'\n# another client\n[mcp_servers.foreign]\ncommand = "foreign"\n'
    path.write_bytes(path.read_bytes() + suffix)
    report = reconcile_config_patch(patch)
    assert report.file_state == FileState.STALE
    assert report.keys[0].kind == ConflictKind.CLEAN
    result = apply_config_restore(plan_config_restore(patch))
    assert result.result.status == "succeeded"
    assert path.read_bytes() == original + suffix
    assert "stackwinnow_playwright" not in tomllib.loads(path.read_text())["mcp_servers"]


def test_codex_modified_table_is_preserved_including_dates(tmp_path):
    patch, path, _ = codex_ownership(tmp_path)
    path.write_text(path.read_text() + "last_used = 2026-11-23\n")
    before = path.read_bytes()
    report = reconcile_config_patch(patch)
    assert report.keys[0].kind == ConflictKind.USER_MODIFIED
    result = apply_config_restore(plan_config_restore(patch))
    assert result.result.status == "skipped"
    assert path.read_bytes() == before


def test_codex_reformatted_table_is_conservatively_blocked(tmp_path):
    patch, path, _ = codex_ownership(tmp_path)
    path.write_text(path.read_text().replace('"args" = []', "# keep my comment\nargs = []"))
    before = path.read_bytes()
    plan = plan_config_restore(patch)
    assert plan.blocked
    assert apply_config_restore(plan).result.status == "blocked"
    assert path.read_bytes() == before


def test_foreign_matching_configuration_is_not_adopted(tmp_path):
    patch, path, _ = codex_ownership(tmp_path)
    matching = plan_codex_server(tmp_path, patch.edits[0].written)
    assert not matching.edits
    before = path.read_bytes()
    assert apply_config_restore(plan_config_restore(matching)).result.status == "skipped"
    assert path.read_bytes() == before


@pytest.mark.parametrize("format", ["json", "toml"])
def test_unreadable_configuration_retains_all_runtimes(tmp_path, format):
    if format == "json":
        patch, path = json_ownership(tmp_path)
    else:
        patch, path, _ = codex_ownership(tmp_path)
    path.write_text("not a valid document !!")
    runtime = ".stackwinnow/envs/tool"
    assert plan_config_restore(patch).blocked
    report = referenced_runtime_paths(patch, [runtime])
    assert report.file_state == FileState.UNREADABLE
    assert report.retained_paths == (runtime,)


def test_runtime_references_include_foreign_settings_after_cleanup(tmp_path):
    patch, path, _ = codex_ownership(tmp_path)
    runtime = ".stackwinnow/envs/tool"
    unrelated = ".stackwinnow/envs/other"
    path.write_text(
        path.read_text() + f'\n[mcp_servers.foreign]\ncommand = "{tmp_path / runtime}/bin/server"\n'
    )
    assert apply_config_restore(plan_config_restore(patch)).result.status == "succeeded"
    assert referenced_runtime_paths(patch, [runtime, unrelated]).retained_paths == (runtime,)


def test_published_restore_keeps_original_ownership_if_cleanup_fails(tmp_path, monkeypatch):
    patch, path = json_ownership(tmp_path)
    plan = plan_config_restore(patch)
    real_unlink = os.unlink

    def fail_cleanup(name, *args, **kwargs):
        if str(name).startswith(".stackwinnow-restore-"):
            raise OSError("controlled cleanup failure")
        return real_unlink(name, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", fail_cleanup)
    result = apply_config_restore(plan)
    assert result.result.status == "failed" and result.published
    assert result.plan.ownership == patch
    assert set(result.released_keys) == set(plan.restore_keys)
    assert json.loads(path.read_text())["replace"] is None


def test_failure_before_publication_keeps_ownership_and_file(tmp_path, monkeypatch):
    patch, path = json_ownership(tmp_path)
    before = path.read_bytes()

    def fail_replace(*args, **kwargs):
        raise OSError("controlled publication failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    result = apply_config_restore(plan_config_restore(patch))
    assert result.result.status == "failed" and not result.published
    assert not result.released_keys
    assert result.plan.ownership == patch
    assert path.read_bytes() == before


def test_graphify_and_playwright_tables_restore_sequentially(tmp_path):
    from stackwinnow.configure.codex import apply_graphify_codex_server, plan_graphify_codex_server

    playwright, path, original = codex_ownership(tmp_path)
    graphify = plan_graphify_codex_server(tmp_path, {"command": "managed-graphify", "args": []})
    assert apply_graphify_codex_server(graphify).ownership == graphify
    with project_lock(tmp_path):
        assert apply_config_restore(plan_config_restore(playwright)).result.status == "succeeded"
        assert apply_config_restore(plan_config_restore(graphify)).result.status == "succeeded"
    assert path.read_bytes() == original


def test_runtime_reference_through_foreign_symlink_is_retained(tmp_path):
    patch, path = json_ownership(tmp_path)
    runtime = tmp_path / ".stackwinnow/envs/tool"
    runtime.mkdir(parents=True)
    alias = tmp_path / "client-alias"
    alias.symlink_to(runtime, target_is_directory=True)
    path.write_text(json.dumps({"foreign": {"command": str(alias / "bin/server")}}))
    assert referenced_runtime_paths(patch, [str(runtime)]).retained_paths == (str(runtime),)


def test_tampered_restore_plan_is_rejected(tmp_path):
    patch, path = json_ownership(tmp_path)
    before = path.read_bytes()
    plan = plan_config_restore(patch).model_copy(update={"restore_keys": ()})
    assert apply_config_restore(plan).result.status == "blocked"
    assert path.read_bytes() == before


def test_existing_user_file_remains_when_owned_values_are_removed(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{}")
    patch = plan_json_edits(
        tmp_path,
        path.name,
        tool_id="test-tool",
        edits=[JsonConfigEdit(key_path=("owned",), value="value")],
    )
    apply_json_edits(patch)
    assert apply_config_restore(plan_config_restore(patch)).result.status == "succeeded"
    assert path.exists() and json.loads(path.read_text()) == {}

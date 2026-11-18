"""Configuration outcomes use copied projects; no assistant or tool is executed."""

import errno
import hashlib
import json
import os
import stat
from pathlib import Path

import pytest
from conftest import FixtureProject
from pydantic import ValidationError

from stackwinnow.configure import (
    ConfigurationConflict,
    ConfigurationError,
    apply_json_edits,
    patches,
    plan_json_edits,
)
from stackwinnow.contracts import ConfigApplyResult, ConfigPatch, JsonConfigEdit

pytestmark = pytest.mark.skipif(os.name != "posix", reason="JSON writes require POSIX file APIs")


def server_edit() -> JsonConfigEdit:
    return JsonConfigEdit(
        key_path=("mcpServers", "fixture-tool"),
        value={"command": "fixture-only-do-not-execute", "args": ["path with spaces"]},
    )


def preview(project: FixtureProject, *edits: JsonConfigEdit) -> ConfigPatch:
    return plan_json_edits(
        project.root, project.settings.name, tool_id="fixture-tool", edits=edits or [server_edit()]
    )


def assert_no_staging_files(directory: Path) -> None:
    assert list(directory.glob(".stackwinnow-*.tmp")) == []


def test_preview_can_be_persisted_before_any_mutation(fixture_project: FixtureProject) -> None:
    original = fixture_project.settings.read_bytes()
    before = set(fixture_project.root.rglob("*"))

    patch = preview(fixture_project)
    restored = ConfigPatch.model_validate_json(patch.model_dump_json())

    assert restored == patch
    assert fixture_project.settings.read_bytes() == original
    assert set(fixture_project.root.rglob("*")) == before
    assert patch.project_root == str(fixture_project.root.resolve())
    assert patch.expected_file.sha256 == hashlib.sha256(original).hexdigest()
    assert patch.expected_file.exists
    assert patch.edits[0].key_path == ("mcpServers", "fixture-tool")
    assert not patch.edits[0].original.exists
    assert patch.edits[0].original.value is None
    assert patch.created_objects == ()


def test_preview_survives_sorted_json_serialization(fixture_project: FixtureProject) -> None:
    value = {
        "command": "fixture-only-do-not-execute",
        "env": {"Z_LAST": "last", "A_FIRST": "first"},
        "args": ["second", "first"],
    }
    patch = preview(
        fixture_project, JsonConfigEdit(key_path=("mcpServers", "fixture-tool"), value=value)
    )
    serialized = json.dumps(patch.model_dump(mode="json"), sort_keys=True)
    restored = ConfigPatch.model_validate_json(serialized)
    assert restored == patch

    outcome = apply_json_edits(restored)

    assert outcome.result.status == "succeeded"
    assert outcome.ownership == patch
    actual = fixture_project.settings.read_bytes()
    assert hashlib.sha256(actual).hexdigest() == patch.written_file.sha256
    assert json.loads(actual)["mcpServers"]["fixture-tool"] == value
    assert_no_staging_files(fixture_project.root)


def test_apply_preserves_unrelated_settings_and_permissions(
    fixture_project: FixtureProject,
) -> None:
    original = json.loads(fixture_project.settings.read_text())
    fixture_project.settings.chmod(0o640)
    patch = preview(fixture_project)

    outcome = apply_json_edits(patch)

    actual = json.loads(fixture_project.settings.read_text())
    assert actual == {
        **original,
        "mcpServers": {**original["mcpServers"], "fixture-tool": server_edit().value},
    }
    assert outcome.result.status == "succeeded"
    assert outcome.ownership == patch
    assert stat.S_IMODE(fixture_project.settings.stat().st_mode) == 0o640
    assert (
        patch.written_file.sha256
        == hashlib.sha256(fixture_project.settings.read_bytes()).hexdigest()
    )
    assert ConfigApplyResult.model_validate_json(outcome.model_dump_json()) == outcome
    assert_no_staging_files(fixture_project.root)


def test_leaf_replacement_keeps_other_fields_of_existing_server(
    fixture_project: FixtureProject,
) -> None:
    original = json.loads(fixture_project.settings.read_text())
    patch = preview(
        fixture_project,
        JsonConfigEdit(
            key_path=("mcpServers", "existing-fixture-server", "command"),
            value="another-fixture-command",
            replace_existing=True,
        ),
    )

    outcome = apply_json_edits(patch)

    actual = json.loads(fixture_project.settings.read_text())
    expected = original["mcpServers"]["existing-fixture-server"]
    assert actual["mcpServers"]["existing-fixture-server"] == {
        **expected,
        "command": "another-fixture-command",
    }
    assert actual["theme"] == original["theme"]
    assert outcome.ownership.edits[0].original.exists
    assert outcome.ownership.edits[0].original.value == expected["command"]


def test_ownership_distinguishes_missing_and_null(fixture_project: FixtureProject) -> None:
    fixture_project.settings.write_text('{"present": null, "unrelated": [1, true]}')
    patch = preview(
        fixture_project,
        JsonConfigEdit(key_path=("missing",), value=None),
        JsonConfigEdit(key_path=("present",), value="configured", replace_existing=True),
    )

    outcome = apply_json_edits(patch)

    missing, present = outcome.ownership.edits
    assert missing.original.exists is False
    assert missing.original.value is None
    assert missing.written is None
    assert present.original.exists is True
    assert present.original.value is None
    assert json.loads(fixture_project.settings.read_text()) == {
        "missing": None,
        "present": "configured",
        "unrelated": [1, True],
    }


@pytest.mark.parametrize(("before", "after"), [(True, 1), (1, True), (1, 1.0), (False, 0)])
def test_json_value_types_are_not_confused_by_python_equality(
    fixture_project: FixtureProject, before: object, after: object
) -> None:
    fixture_project.settings.write_text(json.dumps({"value": before}))
    patch = preview(
        fixture_project,
        JsonConfigEdit(key_path=("value",), value=after, replace_existing=True),
    )
    outcome = apply_json_edits(patch)
    actual = json.loads(fixture_project.settings.read_text())["value"]
    assert outcome.result.status == "succeeded"
    assert type(actual) is type(after)
    assert actual == after


def test_matching_values_are_not_rewritten_or_adopted(fixture_project: FixtureProject) -> None:
    original = b'{"server":{"command":"existing","args":[]}, "theme":"keep"}'
    fixture_project.settings.write_bytes(original)
    before = fixture_project.settings.stat()
    patch = preview(
        fixture_project,
        JsonConfigEdit(key_path=("server",), value={"args": [], "command": "existing"}),
    )

    outcome = apply_json_edits(patch)

    assert outcome.result.status == "skipped"
    assert outcome.ownership is None
    assert patch.edits == ()
    assert patch.expected_file == patch.written_file
    assert fixture_project.settings.read_bytes() == original
    assert fixture_project.settings.stat().st_mtime_ns == before.st_mtime_ns
    assert_no_staging_files(fixture_project.root)


def test_mixed_noop_and_new_edit_only_owns_the_new_value(fixture_project: FixtureProject) -> None:
    patch = preview(
        fixture_project,
        JsonConfigEdit(key_path=("theme",), value="keep-existing-theme"),
        server_edit(),
    )
    outcome = apply_json_edits(patch)
    assert [edit.key_path for edit in outcome.ownership.edits] == [("mcpServers", "fixture-tool")]


def test_new_file_tracks_creation_and_empty_parents(fixture_project: FixtureProject) -> None:
    target = fixture_project.root / "new settings.json"
    edits = [
        JsonConfigEdit(key_path=("mcpServers", "fixture-tool", "command"), value="fixture-only"),
        JsonConfigEdit(key_path=("mcpServers", "fixture-tool", "args"), value=[]),
    ]
    patch = plan_json_edits(fixture_project.root, target.name, tool_id="fixture-tool", edits=edits)
    assert not target.exists()
    assert not patch.expected_file.exists
    assert patch.created_objects == (("mcpServers",), ("mcpServers", "fixture-tool"))

    outcome = apply_json_edits(patch)

    assert outcome.result.status == "succeeded"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert target.stat().st_nlink == 1
    assert json.loads(target.read_text()) == {
        "mcpServers": {"fixture-tool": {"command": "fixture-only", "args": []}}
    }
    assert apply_json_edits(patch).result.status == "blocked"
    again = plan_json_edits(fixture_project.root, target.name, tool_id="fixture-tool", edits=edits)
    assert apply_json_edits(again).result.status == "skipped"
    assert_no_staging_files(fixture_project.root)


def test_empty_request_does_not_create_a_missing_file(fixture_project: FixtureProject) -> None:
    patch = plan_json_edits(fixture_project.root, "absent.json", tool_id="fixture-tool", edits=[])
    assert apply_json_edits(patch).result.status == "skipped"
    assert not (fixture_project.root / "absent.json").exists()


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not json",
        b"[]",
        b"null",
        b"{} trailing",
        b'{"x": 1,}',
        b'{/* keep comment */ "x": 1}',
        b"\xff",
        b'{"x": 1, "x": 2}',
        b'{"nested": [{"x": 1, "x": 2}]}',
        b'{"x": NaN}',
        b'{"x": Infinity}',
        b'{"nested": [1e999]}',
    ],
)
def test_malformed_or_unsupported_input_is_preserved(
    fixture_project: FixtureProject, raw: bytes
) -> None:
    fixture_project.settings.write_bytes(raw)
    with pytest.raises(ConfigurationConflict, match="UTF-8 JSON"):
        preview(fixture_project)
    assert fixture_project.settings.read_bytes() == raw
    assert_no_staging_files(fixture_project.root)


def test_existing_value_needs_explicit_replacement_and_diagnostics_omit_values(
    fixture_project: FixtureProject,
) -> None:
    raw = b'{"credential":"synthetic-private-value"}'
    fixture_project.settings.write_bytes(raw)
    with pytest.raises(ConfigurationConflict) as caught:
        preview(fixture_project, JsonConfigEdit(key_path=("credential",), value="replacement"))
    assert "synthetic-private-value" not in str(caught.value)
    assert "explicitly request replacement" in str(caught.value)
    assert fixture_project.settings.read_bytes() == raw


@pytest.mark.parametrize("parent", [None, [], "existing", 1])
def test_nonobject_parent_is_a_conflict_without_partial_edits(
    fixture_project: FixtureProject, parent: object
) -> None:
    raw = json.dumps({"mcpServers": parent}).encode()
    fixture_project.settings.write_bytes(raw)
    with pytest.raises(ConfigurationConflict, match="parent is not a JSON object"):
        preview(fixture_project, JsonConfigEdit(key_path=("new",), value=1), server_edit())
    assert fixture_project.settings.read_bytes() == raw


@pytest.mark.parametrize(
    "paths",
    [[("x",), ("x",)], [("x",), ("x", "child")], [("x", "child"), ("x",)]],
)
def test_overlapping_edits_are_rejected_before_any_write(
    fixture_project: FixtureProject, paths: list[tuple[str, ...]]
) -> None:
    raw = fixture_project.settings.read_bytes()
    with pytest.raises(ConfigurationConflict, match="overlap"):
        preview(fixture_project, *(JsonConfigEdit(key_path=path, value={}) for path in paths))
    assert fixture_project.settings.read_bytes() == raw


@pytest.mark.parametrize("change", ["unrelated-key", "whitespace", "malformed", "deleted", "mode"])
def test_changes_since_preview_block_apply_and_preserve_current_state(
    fixture_project: FixtureProject, change: str
) -> None:
    patch = preview(fixture_project)
    target = fixture_project.settings
    if change == "unrelated-key":
        data = json.loads(target.read_text())
        data["theme"] = "user-edited-theme"
        target.write_text(json.dumps(data))
    elif change == "whitespace":
        target.write_bytes(target.read_bytes() + b"\n")
    elif change == "malformed":
        target.write_bytes(b"{user is still editing")
    elif change == "deleted":
        target.unlink()
    else:
        target.chmod(0o600 if patch.expected_file.mode != 0o600 else 0o644)
    current = target.read_bytes() if target.exists() else None
    mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else None

    outcome = apply_json_edits(patch)

    assert outcome.result.status == "blocked"
    assert outcome.ownership is None
    assert outcome.result.errors
    assert (target.read_bytes() if target.exists() else None) == current
    assert (stat.S_IMODE(target.stat().st_mode) if target.exists() else None) == mode
    assert_no_staging_files(fixture_project.root)


def test_file_appearing_after_preview_is_not_overwritten(fixture_project: FixtureProject) -> None:
    target = fixture_project.root / "appeared.json"
    patch = plan_json_edits(
        fixture_project.root, target.name, tool_id="fixture-tool", edits=[server_edit()]
    )
    target.write_text('{"user":"keep"}')
    outcome = apply_json_edits(patch)
    assert outcome.result.status == "blocked"
    assert outcome.ownership is None
    assert target.read_text() == '{"user":"keep"}'


@pytest.mark.parametrize("operation", ["fchmod", "fsync", "replace"])
def test_write_failure_leaves_original_intact_and_removes_staging_file(
    fixture_project: FixtureProject, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    raw = fixture_project.settings.read_bytes()
    before = fixture_project.settings.stat()
    patch = preview(fixture_project)

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError(errno.ENOSPC, "synthetic filesystem failure")

    monkeypatch.setattr(patches.os, operation, fail)
    outcome = apply_json_edits(patch)

    assert outcome.result.status == "failed"
    assert outcome.ownership is None
    assert fixture_project.settings.read_bytes() == raw
    assert fixture_project.settings.stat().st_mode == before.st_mode
    assert fixture_project.settings.stat().st_mtime_ns == before.st_mtime_ns
    assert_no_staging_files(fixture_project.root)


def test_edit_during_staging_is_detected_by_final_check(
    fixture_project: FixtureProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch = preview(fixture_project)
    fsync = os.fsync

    def user_edit(descriptor: int) -> None:
        fsync(descriptor)
        fixture_project.settings.write_text('{"user":"changed during apply"}')

    monkeypatch.setattr(patches.os, "fsync", user_edit)
    outcome = apply_json_edits(patch)
    assert outcome.result.status == "blocked"
    assert outcome.ownership is None
    assert fixture_project.settings.read_text() == '{"user":"changed during apply"}'
    assert_no_staging_files(fixture_project.root)


def test_atomic_creation_does_not_clobber_a_last_moment_new_file(
    fixture_project: FixtureProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = fixture_project.root / "new.json"
    patch = plan_json_edits(
        fixture_project.root, target.name, tool_id="fixture-tool", edits=[server_edit()]
    )
    link = os.link

    def competing_create(*args: object, **kwargs: object) -> None:
        target.write_text('{"user":"keep"}')
        link(*args, **kwargs)

    monkeypatch.setattr(patches.os, "link", competing_create)
    outcome = apply_json_edits(patch)
    assert outcome.result.status == "blocked"
    assert outcome.ownership is None
    assert target.read_text() == '{"user":"keep"}'
    assert_no_staging_files(fixture_project.root)


def test_cleanup_failure_after_publication_keeps_actual_ownership(
    fixture_project: FixtureProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = fixture_project.root / "new.json"
    patch = plan_json_edits(
        fixture_project.root, target.name, tool_id="fixture-tool", edits=[server_edit()]
    )
    unlink = os.unlink

    def fail_cleanup(path: str, **kwargs: object) -> None:
        if path.startswith(".stackwinnow-"):
            raise PermissionError(errno.EACCES, "synthetic cleanup failure")
        unlink(path, **kwargs)

    with monkeypatch.context() as changes:
        changes.setattr(patches.os, "unlink", fail_cleanup)
        outcome = apply_json_edits(patch)
    assert outcome.result.status == "failed"
    assert outcome.ownership == patch
    assert "was applied" in outcome.result.message
    assert json.loads(target.read_text())["mcpServers"]["fixture-tool"] == server_edit().value
    for temporary in fixture_project.root.glob(".stackwinnow-*.tmp"):
        temporary.unlink()


@pytest.mark.parametrize(
    "relative_path", ["../outside.json", "/outside.json", ".", "a/../../x.json"]
)
def test_paths_outside_project_scope_are_rejected(
    fixture_project: FixtureProject, relative_path: str
) -> None:
    with pytest.raises(ValidationError, match="project-relative"):
        plan_json_edits(
            fixture_project.root, relative_path, tool_id="fixture-tool", edits=[server_edit()]
        )
    assert_no_staging_files(fixture_project.root)


@pytest.mark.parametrize("kind", ["file", "dangling", "parent", "hard-link", "directory", "fifo"])
def test_linked_or_special_targets_are_rejected_without_touching_other_data(
    fixture_project: FixtureProject, tmp_path: Path, kind: str
) -> None:
    external = tmp_path / "outside project"
    external.mkdir()
    outside = external / "settings.json"
    outside.write_text('{"outside":"keep"}')
    target = fixture_project.root / "linked.json"
    if kind == "file":
        target.symlink_to(outside)
    elif kind == "dangling":
        target.symlink_to(external / "missing.json")
    elif kind == "parent":
        target.symlink_to(external, target_is_directory=True)
        target = target / "settings.json"
    elif kind == "hard-link":
        os.link(outside, target)
    elif kind == "directory":
        target.mkdir()
    else:
        os.mkfifo(target)
    with pytest.raises(ConfigurationConflict):
        plan_json_edits(
            fixture_project.root,
            target.relative_to(fixture_project.root),
            tool_id="fixture-tool",
            edits=[server_edit()],
        )
    assert outside.read_text() == '{"outside":"keep"}'
    assert not (external / "missing.json").exists()
    assert_no_staging_files(fixture_project.root)


def test_parent_replaced_by_symlink_during_apply_does_not_redirect_the_write(
    fixture_project: FixtureProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = fixture_project.root / "settings"
    parent.mkdir()
    (parent / "config.json").write_text('{"original":true}')
    external = tmp_path / "external"
    external.mkdir()
    (external / "config.json").write_text('{"outside":true}')
    patch = plan_json_edits(
        fixture_project.root,
        "settings/config.json",
        tool_id="fixture-tool",
        edits=[server_edit()],
    )
    moved = fixture_project.root / "moved settings"
    fsync = os.fsync

    def replace_parent(descriptor: int) -> None:
        fsync(descriptor)
        parent.rename(moved)
        parent.symlink_to(external, target_is_directory=True)

    monkeypatch.setattr(patches.os, "fsync", replace_parent)
    outcome = apply_json_edits(patch)
    assert outcome.result.status == "blocked"
    assert outcome.ownership is None
    assert (external / "config.json").read_text() == '{"outside":true}'
    assert (moved / "config.json").read_text() == '{"original":true}'
    assert_no_staging_files(external)
    assert_no_staging_files(moved)


def test_missing_parent_is_reported_without_creating_directories(
    fixture_project: FixtureProject,
) -> None:
    with pytest.raises(ConfigurationError, match="parent must exist"):
        plan_json_edits(
            fixture_project.root,
            "missing/config.json",
            tool_id="fixture-tool",
            edits=[server_edit()],
        )
    assert not (fixture_project.root / "missing").exists()


def test_changed_project_ancestor_cannot_redirect_apply(tmp_path: Path) -> None:
    parent = tmp_path / "projects"
    root = parent / "selected"
    root.mkdir(parents=True)
    (root / "settings.json").write_text("{}")
    patch = plan_json_edits(root, "settings.json", tool_id="fixture-tool", edits=[server_edit()])
    parent.rename(tmp_path / "moved projects")
    external = tmp_path / "other projects"
    (external / "selected").mkdir(parents=True)
    outside = external / "selected" / "settings.json"
    outside.write_text("{}")
    parent.symlink_to(external, target_is_directory=True)
    outcome = apply_json_edits(patch)
    assert outcome.result.status == "blocked"
    assert outcome.ownership is None
    assert outside.read_text() == "{}"
    assert_no_staging_files(outside.parent)


def test_plan_rejects_project_symlink_loop(fixture_project: FixtureProject) -> None:
    original = fixture_project.settings.read_bytes()
    moved = fixture_project.root.with_name("moved project")
    fixture_project.root.rename(moved)
    fixture_project.root.symlink_to(fixture_project.root.name, target_is_directory=True)

    with pytest.raises(ConfigurationConflict, match="symlink loop"):
        preview(fixture_project)

    assert (moved / fixture_project.settings.name).read_bytes() == original
    assert_no_staging_files(moved)


def test_apply_blocks_project_symlink_loop(fixture_project: FixtureProject) -> None:
    patch = preview(fixture_project)
    original = fixture_project.settings.read_bytes()
    moved = fixture_project.root.with_name("moved project")
    fixture_project.root.rename(moved)
    fixture_project.root.symlink_to(fixture_project.root.name, target_is_directory=True)

    outcome = apply_json_edits(patch)

    assert outcome.result.status == "blocked"
    assert "symlink loop" in outcome.result.message
    assert outcome.ownership is None
    assert (moved / fixture_project.settings.name).read_bytes() == original
    assert_no_staging_files(moved)


def test_parent_disappearing_after_preview_is_a_conflict(fixture_project: FixtureProject) -> None:
    parent = fixture_project.root / "settings"
    parent.mkdir()
    patch = plan_json_edits(
        fixture_project.root, "settings/new.json", tool_id="fixture-tool", edits=[server_edit()]
    )
    parent.rmdir()
    outcome = apply_json_edits(patch)
    assert outcome.result.status == "blocked"
    assert outcome.ownership is None
    assert not parent.exists()


@pytest.mark.parametrize(
    "number", ["1e-999", "0.12345678901234567890123456789", "1e-999999999999999999999999"]
)
def test_unrelated_numbers_are_not_silently_rounded(
    fixture_project: FixtureProject, number: str
) -> None:
    raw = '{"unrelated":' + number + "}"
    fixture_project.settings.write_text(raw)
    with pytest.raises(ConfigurationConflict, match="precision loss"):
        preview(fixture_project)
    assert fixture_project.settings.read_text() == raw


def test_round_tripped_patch_uses_original_project_after_cwd_changes(
    fixture_project: FixtureProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch = ConfigPatch.model_validate_json(preview(fixture_project).model_dump_json())
    other = tmp_path / "another project"
    other.mkdir()
    unrelated = other / fixture_project.settings.name
    unrelated.write_text('{"other":true}')
    monkeypatch.chdir(other)
    assert apply_json_edits(patch).result.status == "succeeded"
    assert unrelated.read_text() == '{"other":true}'


def test_request_mutation_cannot_change_an_already_created_preview(
    fixture_project: FixtureProject,
) -> None:
    request = server_edit()
    patch = preview(fixture_project, request)
    request.value["args"].append("later change")
    assert apply_json_edits(patch).result.status == "succeeded"
    assert json.loads(fixture_project.settings.read_text())["mcpServers"]["fixture-tool"][
        "args"
    ] == ["path with spaces"]


@pytest.mark.parametrize(
    "changed", ["written-value", "original-value", "output-hash", "created-objects", "contract"]
)
def test_modified_preview_is_rejected_without_writing(
    fixture_project: FixtureProject, changed: str
) -> None:
    patch = preview(
        fixture_project, JsonConfigEdit(key_path=("theme",), value="new", replace_existing=True)
    )
    data = patch.model_dump(mode="json")
    if changed == "written-value":
        data["edits"][0]["written"] = "different from preview"
    elif changed == "original-value":
        data["edits"][0]["original"]["value"] = "not the original"
    elif changed == "output-hash":
        data["written_file"]["sha256"] = "0" * 64
    elif changed == "created-objects":
        data["created_objects"] = [["unowned"]]
    else:
        data["relative_path"] = "../outside.json"
    # model_construct deliberately represents an unchecked/mutated caller input.
    unchecked = ConfigPatch.model_construct(**data)
    original = fixture_project.settings.read_bytes()
    outcome = apply_json_edits(unchecked)
    assert outcome.result.status == "blocked"
    assert outcome.ownership is None
    assert fixture_project.settings.read_bytes() == original
    assert_no_staging_files(fixture_project.root)


def test_json_keys_are_literal_and_unicode_values_round_trip(
    fixture_project: FixtureProject,
) -> None:
    patch = preview(
        fixture_project,
        JsonConfigEdit(key_path=("options", "literal/key.name", ""), value="नमस्ते 🌱"),
    )
    assert apply_json_edits(patch).result.status == "succeeded"
    assert (
        json.loads(fixture_project.settings.read_text())["options"]["literal/key.name"][""]
        == "नमस्ते 🌱"
    )


@pytest.mark.parametrize("value", [float("nan"), {"nested": [float("inf")]}, {1: "non-string key"}])
def test_non_json_edit_values_cannot_enter_a_preview(value: object) -> None:
    with pytest.raises(ValidationError):
        JsonConfigEdit(key_path=("value",), value=value)

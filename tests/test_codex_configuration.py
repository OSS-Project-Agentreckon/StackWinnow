import json
import os
import tomllib

import pytest

from stackwinnow.configure import apply_json_edits
from stackwinnow.configure.codex import SERVER, apply_codex_server, plan_codex_server
from stackwinnow.configure.patches import ConfigurationConflict
from stackwinnow.contracts import ConfigPatch

SETTINGS = {
    "command": "/path with spaces/node",
    "args": ['hello "world"', "a\\b"],
    "env": {"HOME": "/private/home"},
    "enabled": True,
}


def test_preview_missing_parent_is_read_only(tmp_path):
    patch = plan_codex_server(tmp_path, SETTINGS)
    assert not list(tmp_path.iterdir())
    assert patch.format == "toml"
    assert not patch.expected_file.exists
    assert apply_codex_server(patch).result.status == "blocked"
    assert not list(tmp_path.iterdir())


def test_append_preserves_bytes_and_mode(tmp_path):
    (tmp_path / ".codex").mkdir()
    path = tmp_path / ".codex/config.toml"
    original = (
        b'# user comment\nmodel = "user-model"\n[mcp_servers.other]\ncommand = "other" # keep\n'
    )
    path.write_bytes(original)
    path.chmod(0o640)
    patch = plan_codex_server(tmp_path, SETTINGS)
    patch = ConfigPatch.model_validate_json(
        json.dumps(patch.model_dump(mode="json"), sort_keys=True)
    )
    result = apply_codex_server(patch)
    assert result.result.status == "succeeded"
    assert result.ownership == patch
    assert path.read_bytes().startswith(original)
    assert path.stat().st_mode & 0o777 == 0o640
    assert tomllib.loads(path.read_text())["mcp_servers"][SERVER] == SETTINGS
    noop = plan_codex_server(tmp_path, SETTINGS)
    assert not noop.edits
    assert apply_codex_server(noop).ownership is None


@pytest.mark.parametrize(
    "original", [b"mcp_servers = 3", b"mcp_servers = {}", b'model = "a"\nmodel = "b"', b"\xff"]
)
def test_invalid_or_sealed_parent_is_preserved(tmp_path, original):
    (tmp_path / ".codex").mkdir()
    path = tmp_path / ".codex/config.toml"
    path.write_bytes(original)
    with pytest.raises(ConfigurationConflict):
        plan_codex_server(tmp_path, SETTINGS)
    assert path.read_bytes() == original


def test_stale_or_tampered_preview_and_wrong_writer(tmp_path):
    (tmp_path / ".codex").mkdir()
    patch = plan_codex_server(tmp_path, SETTINGS)
    assert apply_json_edits(patch).result.status == "blocked"
    tampered = patch.model_copy(update={"created_objects": ()})
    assert apply_codex_server(tampered).result.status == "blocked"
    path = tmp_path / ".codex/config.toml"
    path.write_text("# appeared\n")
    assert apply_codex_server(patch).result.status == "blocked"
    assert path.read_text() == "# appeared\n"


@pytest.mark.parametrize(
    "kind", ["parent-symlink", "file-symlink", "hardlink", "fifo", "oversized"]
)
def test_unsafe_paths(tmp_path, kind):
    outside = tmp_path / "outside"
    outside.mkdir()
    parent = tmp_path / ".codex"
    if kind == "parent-symlink":
        parent.symlink_to(outside, target_is_directory=True)
    else:
        parent.mkdir()
        path = parent / "config.toml"
        if kind == "file-symlink":
            path.symlink_to(outside / "missing")
        elif kind == "hardlink":
            (outside / "target").write_text("")
            os.link(outside / "target", path)
        elif kind == "fifo":
            os.mkfifo(path)
        else:
            path.write_bytes(b"#" * (4 * 1024 * 1024 + 1))
    with pytest.raises(ConfigurationConflict):
        plan_codex_server(tmp_path, SETTINGS)


def test_toml_publication_cleanup_failure_retains_ownership(tmp_path, monkeypatch):
    from stackwinnow.configure import patches

    (tmp_path / ".codex").mkdir()
    patch = plan_codex_server(tmp_path, SETTINGS)
    original = patches.os.unlink

    def fail_cleanup(path, **kwargs):
        if str(path).startswith(".stackwinnow-"):
            raise PermissionError(13, "fixture cleanup denied")
        return original(path, **kwargs)

    monkeypatch.setattr(patches.os, "unlink", fail_cleanup)
    result = apply_codex_server(patch)
    assert result.result.status == "failed"
    assert result.ownership == patch
    assert (
        tomllib.loads((tmp_path / ".codex/config.toml").read_text())["mcp_servers"][SERVER]
        == SETTINGS
    )

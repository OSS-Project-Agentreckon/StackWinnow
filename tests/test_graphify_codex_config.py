"""Failing tests for B03 — Graphify Codex configuration and ownership.

These are written before the implementation so the CI check is red first.
Once plan_graphify_codex_server / apply_graphify_codex_server exist and
graphify_install.py wires up configuration_intents, all tests should pass.
"""

from __future__ import annotations

import tomllib

import pytest

from stackwinnow.configure.patches import ConfigurationConflict
from stackwinnow.contracts import ConfigPatch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GRAPHIFY_SETTINGS = {
    "command": "/path/to/python",
    "args": ["-I", "-m", "graphify", "mcp", "--graph", "/path/to/graph.json"],
    "env": {"HOME": "/private/home", "GRAPHIFY_NO_AUTO_REFRESH": "1"},
}


# ---------------------------------------------------------------------------
# 1. Module-level constants
# ---------------------------------------------------------------------------


def test_graphify_server_constant_is_stackwinnow_graphify():
    """The registered MCP server name must be 'stackwinnow_graphify'."""
    from stackwinnow.configure.codex import GRAPHIFY_SERVER

    assert GRAPHIFY_SERVER == "stackwinnow_graphify"


# ---------------------------------------------------------------------------
# 2. plan_graphify_codex_server — preview (read-only)
# ---------------------------------------------------------------------------


def test_plan_graphify_codex_server_returns_toml_patch(tmp_path):
    """Preview call must return a ConfigPatch in TOML format without touching disk."""
    from stackwinnow.configure.codex import plan_graphify_codex_server

    patch = plan_graphify_codex_server(tmp_path, GRAPHIFY_SETTINGS)

    assert not list(tmp_path.iterdir())
    assert isinstance(patch, ConfigPatch)
    assert patch.format == "toml"
    assert patch.relative_path == ".codex/config.toml"
    assert patch.tool_id == "graphify"


def test_plan_graphify_codex_server_has_one_edit_for_new_file(tmp_path):
    """When the file is absent, the preview records exactly one pending edit."""
    from stackwinnow.configure.codex import GRAPHIFY_KEY, plan_graphify_codex_server

    patch = plan_graphify_codex_server(tmp_path, GRAPHIFY_SETTINGS)

    assert len(patch.edits) == 1
    assert patch.edits[0].key_path == GRAPHIFY_KEY


def test_plan_graphify_codex_server_no_edits_when_already_registered(tmp_path):
    """When the server entry already matches, preview returns an empty-edits patch."""
    from stackwinnow.configure.codex import (
        apply_graphify_codex_server,
        plan_graphify_codex_server,
    )

    (tmp_path / ".codex").mkdir()
    first = plan_graphify_codex_server(tmp_path, GRAPHIFY_SETTINGS)
    apply_graphify_codex_server(first)

    noop = plan_graphify_codex_server(tmp_path, GRAPHIFY_SETTINGS)

    assert noop.edits == ()
    result = apply_graphify_codex_server(noop)
    assert result.ownership is None


# ---------------------------------------------------------------------------
# 3. apply_graphify_codex_server — write path
# ---------------------------------------------------------------------------


def test_apply_graphify_codex_server_creates_toml_entry(tmp_path):
    """Applying the patch must write a parseable TOML file containing the server."""
    from stackwinnow.configure.codex import (
        GRAPHIFY_SERVER,
        apply_graphify_codex_server,
        plan_graphify_codex_server,
    )

    (tmp_path / ".codex").mkdir()
    patch = plan_graphify_codex_server(tmp_path, GRAPHIFY_SETTINGS)
    result = apply_graphify_codex_server(patch)

    assert result.result.status == "succeeded"
    assert result.ownership == patch
    toml = tomllib.loads((tmp_path / ".codex/config.toml").read_text())
    assert toml["mcp_servers"][GRAPHIFY_SERVER] == GRAPHIFY_SETTINGS


def test_apply_graphify_codex_server_blocked_when_parent_absent(tmp_path):
    """When .codex/ does not exist, apply must return blocked without creating files."""
    from stackwinnow.configure.codex import (
        apply_graphify_codex_server,
        plan_graphify_codex_server,
    )

    patch = plan_graphify_codex_server(tmp_path, GRAPHIFY_SETTINGS)
    result = apply_graphify_codex_server(patch)

    assert result.result.status == "blocked"
    assert not (tmp_path / ".codex").exists()


def test_apply_graphify_codex_server_preserves_existing_bytes_and_mode(tmp_path):
    """Appending must not alter existing content or file permissions."""
    from stackwinnow.configure.codex import (
        GRAPHIFY_SERVER,
        apply_graphify_codex_server,
        plan_graphify_codex_server,
    )

    (tmp_path / ".codex").mkdir()
    path = tmp_path / ".codex/config.toml"
    original = b'# comment\nmodel = "gpt-4"\n[mcp_servers.other]\ncommand = "other"\n'
    path.write_bytes(original)
    path.chmod(0o640)

    patch = plan_graphify_codex_server(tmp_path, GRAPHIFY_SETTINGS)
    apply_graphify_codex_server(patch)

    written = path.read_bytes()
    assert written.startswith(original)
    assert path.stat().st_mode & 0o777 == 0o640
    assert tomllib.loads(written.decode())["mcp_servers"][GRAPHIFY_SERVER] == GRAPHIFY_SETTINGS


# ---------------------------------------------------------------------------
# 4. Conflict / error lifecycle
# ---------------------------------------------------------------------------


def test_lifecycle_conflict_when_entry_differs(tmp_path):
    """When the server table exists but has different content, raise ConfigurationConflict."""
    from stackwinnow.configure.codex import plan_graphify_codex_server

    (tmp_path / ".codex").mkdir()
    path = tmp_path / ".codex/config.toml"
    path.write_text('[mcp_servers.stackwinnow_graphify]\ncommand = "other-python"\n')

    with pytest.raises(ConfigurationConflict):
        plan_graphify_codex_server(tmp_path, GRAPHIFY_SETTINGS)


def test_lifecycle_malformed_toml_raises_conflict(tmp_path):
    """Malformed TOML in the config file must raise ConfigurationConflict."""
    from stackwinnow.configure.codex import plan_graphify_codex_server

    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex/config.toml").write_bytes(b"\xff not utf8")

    with pytest.raises(ConfigurationConflict):
        plan_graphify_codex_server(tmp_path, GRAPHIFY_SETTINGS)


def test_lifecycle_mcp_servers_wrong_type_raises_conflict(tmp_path):
    """When mcp_servers is not a table, raise ConfigurationConflict."""
    from stackwinnow.configure.codex import plan_graphify_codex_server

    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex/config.toml").write_text("mcp_servers = 3\n")

    with pytest.raises(ConfigurationConflict):
        plan_graphify_codex_server(tmp_path, GRAPHIFY_SETTINGS)


def test_lifecycle_stale_patch_is_blocked(tmp_path):
    """A tampered patch (expected sha256 no longer matches disk) must be blocked."""
    from stackwinnow.configure.codex import (
        apply_graphify_codex_server,
        plan_graphify_codex_server,
    )

    (tmp_path / ".codex").mkdir()
    patch = plan_graphify_codex_server(tmp_path, GRAPHIFY_SETTINGS)
    # Someone wrote the file after preview was taken
    (tmp_path / ".codex/config.toml").write_text("# appeared\n")
    result = apply_graphify_codex_server(patch)

    assert result.result.status == "blocked"
    assert (tmp_path / ".codex/config.toml").read_text() == "# appeared\n"


# ---------------------------------------------------------------------------
# 5. graphify_install.py wires configuration_intents
# ---------------------------------------------------------------------------


def test_graphify_install_result_reports_codex_config_limitation_removed(tmp_path):
    """After B03, the 'Codex configuration not implemented' limitation must be absent."""
    from stackwinnow.adapters.graphify_install import GraphifyInstallResult

    limitations_text = " ".join(GraphifyInstallResult.model_fields["limitations"].default)
    assert "not implemented" not in limitations_text.lower()


def test_graphify_server_settings_uses_managed_python(tmp_path):
    """graphify_server_settings must reference the managed Python in INSTALL_ROOT."""
    from stackwinnow.adapters.graphify_install import INSTALL_ROOT, graphify_server_settings

    root = tmp_path
    s = graphify_server_settings(root)

    python_path = str(root / INSTALL_ROOT / "python" / "bin" / "python")
    # The command must be the managed Python inside the graphify environment.
    assert (
        s["command"] == python_path
        or python_path in s.get("args", [])
        or (
            str(root / ".stackwinnow/envs/graphify/python/bin/python")
            in [s.get("command")] + s.get("args", [])
        )
    )

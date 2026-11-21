"""Append one Codex MCP table, preserving every unrelated byte of TOML."""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

from stackwinnow.configure.patches import (
    ConfigurationConflict,
    _apply_edits,
    _json,
    _parent,
    _read,
    _resolve_project_root,
)
from stackwinnow.contracts import (
    ConfigFileState,
    ConfigPatch,
    ConfigValue,
    JsonConfigEdit,
    OwnedConfigEdit,
)

RELATIVE_PATH = ".codex/config.toml"
SERVER = "stackwinnow_playwright"
KEY = ("mcp_servers", SERVER)


def document(raw: bytes | None) -> dict:
    try:
        return tomllib.loads((raw or b"").decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ConfigurationConflict("Codex configuration must be valid UTF-8 TOML.") from exc


def _value(value):
    if isinstance(value, dict):
        return (
            "{ "
            + ", ".join(json.dumps(k) + " = " + _value(v) for k, v in sorted(value.items()))
            + " }"
        )
    if isinstance(value, list):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    if type(value) not in (str, int, bool):
        raise ConfigurationConflict("This Codex writer supports strings, integers and booleans.")
    return json.dumps(value, ensure_ascii=False)


def _prepare(root, relative, tool_id, requests, raw, state):
    if relative != RELATIVE_PATH or tool_id != "playwright-mcp":
        raise ConfigurationConflict("This writer only supports the Playwright Codex registration.")
    parsed = document(raw)
    servers = parsed.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise ConfigurationConflict("mcp_servers must be a TOML table.")
    changes = []
    created = []
    rendered = raw
    written = state
    if len(requests) > 1:
        raise ConfigurationConflict("Only one managed server table can be appended.")
    for request in requests:
        if request.key_path != KEY or not isinstance(request.value, dict):
            raise ConfigurationConflict("Expected one complete Playwright MCP table.")
        if SERVER in servers:
            if _json(servers[SERVER]) != _json(request.value):
                raise ConfigurationConflict("The Playwright MCP table already exists and differs.")
            continue
        suffix = "\n[mcp_servers." + SERVER + "]\n"
        suffix += "".join(
            json.dumps(k) + " = " + _value(v) + "\n" for k, v in sorted(request.value.items())
        )
        rendered = (raw or b"") + suffix.encode("utf-8")
        expected = dict(parsed)
        expected["mcp_servers"] = dict(servers, **{SERVER: request.value})
        if document(rendered) != expected:
            raise ConfigurationConflict("Cannot append this server without changing existing TOML.")
        changes.append(
            OwnedConfigEdit(key_path=KEY, original=ConfigValue(exists=False), written=request.value)
        )
        if "mcp_servers" not in parsed:
            created.append(("mcp_servers",))
        written = ConfigFileState(
            exists=True,
            sha256=hashlib.sha256(rendered).hexdigest(),
            mode=state.mode if state.exists else 0o600,
        )
    return ConfigPatch(
        format="toml",
        project_root=root,
        relative_path=relative,
        tool_id=tool_id,
        expected_file=state,
        written_file=written,
        edits=tuple(changes),
        created_objects=tuple(created),
    ), rendered


def plan_codex_server(project_root: str | Path, settings: dict) -> ConfigPatch:
    root = _resolve_project_root(project_root)
    try:
        with _parent(root, RELATIVE_PATH) as (parent, name):
            raw, state = _read(parent, name, limit=4 * 1024 * 1024)
    except FileNotFoundError:
        # Only the fixed .codex parent may be absent. Apply creates it explicitly.
        raw, state = None, ConfigFileState(exists=False)
    patch, _ = _prepare(
        root,
        RELATIVE_PATH,
        "playwright-mcp",
        [JsonConfigEdit(key_path=KEY, value=settings)],
        raw,
        state,
    )
    return patch


def apply_codex_server(patch: ConfigPatch):
    """Parents must exist; shared atomic writer preserves mode and retains ownership."""
    return _apply_edits(patch, prepare=_prepare, format="toml")

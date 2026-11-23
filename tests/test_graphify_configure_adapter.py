import json
import tomllib

import pytest
from test_graphify_bridge import indexed as _indexed_fixture
from test_graphify_index_adapter import project as _project_fixture

from stackwinnow.adapters import graphify_configure as adapter
from stackwinnow.adapters.graphify import GraphifyError
from stackwinnow.adapters.graphify_index import GRAPH_PATH
from stackwinnow.adapters.graphify_install import MANIFEST, graphify_server_settings
from stackwinnow.configure.codex import (
    GRAPHIFY_SERVER,
    apply_graphify_codex_server,
    plan_graphify_codex_server,
)
from stackwinnow.installer import load_record

project = _project_fixture
indexed = _indexed_fixture


def test_configuration_requires_real_runtime_and_index(project):
    with pytest.raises(GraphifyError):
        adapter.plan_graphify_configure(project)
    assert not (project / ".codex").exists()


def test_configure_preview_dry_run_create_repeat_preserves_ownership(indexed):
    before = {p: p.read_bytes() for p in indexed.rglob("*") if p.is_file()}
    plan = adapter.plan_graphify_configure(indexed)
    dry = adapter.apply_graphify_configure(plan, dry_run=True)
    assert dry.dry_run and not dry.configured
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert not (indexed / ".codex").exists()
    first = adapter.apply_graphify_configure(plan)
    assert first.configured
    path = indexed / ".codex/config.toml"
    original = path.read_bytes()
    assert tomllib.loads(original.decode())["mcp_servers"][
        GRAPHIFY_SERVER
    ] == graphify_server_settings(indexed)
    receipt = first.record.receipt_for(adapter.CONFIGURE_STEP_ID)
    assert receipt.configuration_ownership == [plan.configuration]
    assert receipt.owned_paths == [str(indexed / ".codex")]
    repeated = adapter.apply_graphify_configure(plan)
    assert repeated.configured and repeated.results[0].status == "skipped"
    assert path.read_bytes() == original
    assert repeated.record.receipt_for(adapter.CONFIGURE_STEP_ID) == receipt


@pytest.mark.parametrize("change", ["source", "graph", "manifest", "recipe", "config-before-apply"])
def test_changed_inputs_block_before_configuration_writes(indexed, change):
    plan = adapter.plan_graphify_configure(indexed)
    if change == "source":
        (indexed / "caller.py").write_text("changed")
    elif change == "graph":
        (indexed / GRAPH_PATH).unlink()
    elif change == "manifest":
        (indexed / MANIFEST).write_text("{}")
    elif change == "recipe":
        plan = plan.model_copy(update={"bridge_sha256": "0" * 64})
    else:
        (indexed / ".codex").mkdir()
        (indexed / ".codex/config.toml").write_text("# newly added\n")
    before = (indexed / ".stackwinnow/receipts.json").read_bytes()
    with pytest.raises(GraphifyError):
        adapter.apply_graphify_configure(plan)
    assert (indexed / ".stackwinnow/receipts.json").read_bytes() == before


@pytest.mark.parametrize("change", ["edited", "removed", "malformed", "symlink"])
def test_user_configuration_changes_are_preserved_on_reapply(indexed, change):
    plan = adapter.plan_graphify_configure(indexed)
    assert adapter.apply_graphify_configure(plan).configured
    path = indexed / ".codex/config.toml"
    if change == "edited":
        path.write_text(path.read_text().replace("query_relationship", "different_tool"))
    elif change == "removed":
        path.unlink()
    elif change == "malformed":
        path.write_text("[invalid")
    else:
        path.unlink()
        path.symlink_to(indexed / "caller.py")
    before = path.read_bytes() if path.exists() else None
    receipt_before = (indexed / ".stackwinnow/receipts.json").read_bytes()
    with pytest.raises(GraphifyError):
        adapter.apply_graphify_configure(plan)
    assert (path.read_bytes() if path.exists() else None) == before
    assert (indexed / ".stackwinnow/receipts.json").read_bytes() == receipt_before


def test_unrelated_toml_edits_and_other_tool_survive_reapply(indexed):
    plan = adapter.plan_graphify_configure(indexed)
    assert adapter.apply_graphify_configure(plan).configured
    path = indexed / ".codex/config.toml"
    path.write_text(
        path.read_text() + '\n# user notes\n[mcp_servers.other]\ncommand = "other-tool"\n'
    )
    preserved = path.read_bytes()
    for candidate in (plan, adapter.plan_graphify_configure(indexed)):
        result = adapter.apply_graphify_configure(candidate)
        assert result.configured
        assert result.record.receipt_for(adapter.CONFIGURE_STEP_ID).configuration_ownership == [
            plan.configuration
        ]
        assert result.record.receipt_for(adapter.CONFIGURE_STEP_ID).owned_paths == [
            str(indexed / ".codex")
        ]
        assert path.read_bytes() == preserved


def test_matching_foreign_registration_is_not_adopted(indexed):
    (indexed / ".codex").mkdir()
    assert (
        apply_graphify_codex_server(
            plan_graphify_codex_server(indexed, graphify_server_settings(indexed))
        ).result.status
        == "succeeded"
    )
    before = (indexed / ".stackwinnow/receipts.json").read_bytes()
    with pytest.raises(GraphifyError, match="foreign"):
        adapter.plan_graphify_configure(indexed)
    assert (indexed / ".stackwinnow/receipts.json").read_bytes() == before


def test_unsafe_parent_cannot_redirect_configuration(indexed, tmp_path):
    plan = adapter.plan_graphify_configure(indexed)
    outside = tmp_path / "outside"
    outside.mkdir()
    (indexed / ".codex").symlink_to(outside, target_is_directory=True)
    with pytest.raises(GraphifyError):
        adapter.apply_graphify_configure(plan)
    assert not list(outside.iterdir())


def test_write_failure_keeps_intent_and_created_parent(indexed, monkeypatch):
    plan = adapter.plan_graphify_configure(indexed)

    def fail(patch):
        assert (indexed / ".stackwinnow/operation.lock").exists()
        record = load_record(str(indexed))
        assert record.receipt_for(adapter.CONFIGURE_STEP_ID).configuration_intents == [
            plan.configuration
        ]
        raise OSError("simulated write failure")

    monkeypatch.setattr(adapter, "apply_graphify_codex_server", fail)
    result = adapter.apply_graphify_configure(plan)
    assert not result.configured
    receipt = result.record.receipt_for(adapter.CONFIGURE_STEP_ID)
    assert receipt.status == "failed" and receipt.configuration_intents == [plan.configuration]
    assert receipt.owned_paths == [str(indexed / ".codex")]
    with pytest.raises(GraphifyError):
        adapter.plan_graphify_configure(indexed)


def test_configuration_cli_preview_apply_and_repeat(indexed, tmp_path, capsys):
    from stackwinnow.cli import main

    assert main(["graphify", "configure-plan", str(indexed), "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    source = tmp_path / "configure.json"
    source.write_text(json.dumps(plan))
    assert main(["graphify", "configure", str(source), "--dry-run", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"]
    assert main(["graphify", "configure", str(source), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["configured"]


def test_bridge_registration_never_uses_nonexistent_upstream_mcp_command(indexed):
    settings = graphify_server_settings(indexed)
    assert "stackwinnow.graphify_bridge" in settings["args"]
    assert "mcp" not in settings["args"]

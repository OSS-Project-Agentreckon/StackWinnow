"""Real filesystem cleanup; fixture commands do not prove upstream functionality."""

import json

import pytest

from stackwinnow import _removal_fs, removal
from stackwinnow.cli import main
from stackwinnow.configure import apply_json_edits, plan_json_edits
from stackwinnow.configure.codex import (
    apply_codex_server,
    apply_graphify_codex_server,
    plan_codex_server,
    plan_graphify_codex_server,
)
from stackwinnow.contracts import JsonConfigEdit
from stackwinnow.installer import (
    ExecutionRecord,
    InstallerError,
    StepReceipt,
    _persist,
    load_record,
)


def setup(root, tools, *, configure=True):
    record = ExecutionRecord(project_root=str(root))
    for tool in tools:
        paths = removal.RUNTIMES[tool]
        for relative in paths:
            directory = root / relative
            directory.mkdir(parents=True)
            (directory / "module").write_text("owned runtime")
            (directory / "nested").mkdir()
            (directory / "nested/bin").symlink_to("../module")
        data = root / removal.DATA[tool]
        data.mkdir(parents=True, exist_ok=True)
        (data / "reports").mkdir()
        (data / "reports/keep.json").write_text("user history")
        patch = None
        if configure:
            patch = plan_json_edits(
                root,
                tool + ".json",
                tool_id=tool,
                edits=[
                    JsonConfigEdit(key_path=("server",), value=str(root / paths[0] / "module")),
                ],
            )
            assert apply_json_edits(patch).ownership is not None
        record.steps.append(
            StepReceipt(
                step_id=tool + "-install",
                tool_id=tool,
                status="succeeded",
                message="Fixture installation",
                timestamp="2026-11-23T00:00:00Z",
                owned_paths=[str(root / p) for p in paths] + [str(data)],
                configuration_ownership=[patch] if patch else [],
                configuration_intents=[patch] if patch else [],
            )
        )
    _persist(record, project_root=str(root))
    return record


@pytest.mark.parametrize("tool", list(removal.RUNTIMES))
def test_four_modes_remove_retain_archive_and_repeat(tmp_path, tool):
    setup(tmp_path, [tool])
    before = (tmp_path / ".stackwinnow/receipts.json").read_bytes()
    plan = removal.plan_removal_lifecycle(tmp_path, [tool])
    assert all(r.action == "remove" for r in plan.runtimes)
    assert (tmp_path / ".stackwinnow/receipts.json").read_bytes() == before
    assert not (tmp_path / removal.JOURNALS).exists()
    assert removal.apply_removal(plan, dry_run=True).dry_run
    result = removal.apply_removal(plan)
    assert result.status == "succeeded", (tmp_path / result.journal).read_text()
    assert result.retired_tools == [tool]
    assert all(not (tmp_path / p).exists() for p in removal.RUNTIMES[tool])
    assert (tmp_path / removal.DATA[tool] / "reports/keep.json").read_text() == "user history"
    assert json.loads((tmp_path / (tool + ".json")).read_text()) == {}
    record = load_record(str(tmp_path))
    assert record.steps == []
    assert record.retirements[0].original_steps[0].configuration_ownership
    assert record.retained_path(tool, removal.DATA[tool])
    again = removal.apply_removal(removal.plan_removal_lifecycle(tmp_path, [tool]))
    assert again.status == "skipped"


def test_shared_codex_file_restores_both_tables(tmp_path):
    record = setup(tmp_path, ["graphify", "playwright-mcp"], configure=False)
    (tmp_path / ".codex").mkdir()
    config = tmp_path / ".codex/config.toml"
    original = b"# user comment" + bytes([10]) + b'model = "kept"' + bytes([10])
    config.write_bytes(original)
    for tool, plan, apply in [
        ("graphify", plan_graphify_codex_server, apply_graphify_codex_server),
        ("playwright-mcp", plan_codex_server, apply_codex_server),
    ]:
        patch = plan(tmp_path, {"command": str(tmp_path / removal.RUNTIMES[tool][0] / "module")})
        assert apply(patch).ownership == patch
        record.steps[[s.tool_id for s in record.steps].index(tool)].configuration_ownership = [
            patch
        ]
    _persist(record, project_root=str(tmp_path))
    result = removal.apply_removal(
        removal.plan_removal_lifecycle(tmp_path, ["graphify", "playwright-mcp"])
    )
    assert result.status == "succeeded", (tmp_path / result.journal).read_text()
    assert config.read_bytes() == original
    assert set(result.retired_tools) == {"graphify", "playwright-mcp"}


@pytest.mark.parametrize("kind", ["modified", "foreign", "alias", "failed", "other-tool"])
def test_preserved_references_and_ownership_protect_runtime(tmp_path, kind):
    record = setup(tmp_path, ["headroom"])
    path = tmp_path / "headroom.json"
    data = json.loads(path.read_text())
    runtime = tmp_path / removal.RUNTIMES["headroom"][0]
    if kind == "modified":
        data["server"] = "./indirect-user-wrapper"
    elif kind in {"foreign", "alias"}:
        target = str(runtime / "module")
        if kind == "alias":
            (tmp_path / "alias").symlink_to(runtime, target_is_directory=True)
            target = str(tmp_path / "alias/module")
        data["foreign"] = target
    else:
        record.steps.append(
            StepReceipt(
                step_id="protected",
                tool_id="other" if kind == "other-tool" else "headroom",
                status="failed" if kind == "failed" else "succeeded",
                message="Retained",
                timestamp="now",
                owned_paths=[str(runtime / "module")],
            )
        )
        _persist(record, project_root=str(tmp_path))
    path.write_text(json.dumps(data))
    plan = removal.plan_removal_lifecycle(tmp_path, ["headroom"])
    assert plan.runtimes[0].action == "retain"
    result = removal.apply_removal(plan)
    assert not result.removed_paths and runtime.exists()
    assert not result.retired_tools


@pytest.mark.parametrize(
    "change", ["runtime", "config", "receipt", "duplicate", "forged", "parent"]
)
def test_stale_or_forged_plan_does_not_start_journal(tmp_path, change):
    setup(tmp_path, ["headroom"])
    plan = removal.plan_removal_lifecycle(tmp_path, ["headroom"])
    if change == "runtime":
        (tmp_path / removal.RUNTIMES["headroom"][0] / "module").write_text("changed")
    elif change == "config":
        (tmp_path / "headroom.json").write_text("{}")
    elif change == "receipt":
        record = load_record(str(tmp_path))
        record.steps[0].message = "changed"
        _persist(record, project_root=str(tmp_path))
    elif change == "forged":
        plan.runtimes[0].path = ".stackwinnow/receipts.json"
    elif change == "duplicate":
        file = tmp_path / ".stackwinnow/receipts.json"
        value = json.loads(file.read_text())
        value["steps"].append(value["steps"][0])
        file.write_text(json.dumps(value))
    else:
        path = tmp_path / ".stackwinnow/envs"
        path.rename(tmp_path / "moved")
        path.symlink_to(tmp_path / "moved", target_is_directory=True)
    with pytest.raises((InstallerError, ValueError)):
        removal.apply_removal(plan)
    assert not (tmp_path / removal.JOURNALS).exists()


def test_live_reference_added_after_restore_prevents_deletion(tmp_path, monkeypatch):
    record = setup(tmp_path, ["headroom"])
    record.steps[0].configuration_intents = []
    _persist(record, project_root=str(tmp_path))
    original = removal.apply_config_restore

    def changed(plan):
        outcome = original(plan)
        (tmp_path / "headroom.json").write_text(
            json.dumps({"foreign": str(tmp_path / removal.RUNTIMES["headroom"][0])})
        )
        return outcome

    monkeypatch.setattr(removal, "apply_config_restore", changed)
    result = removal.apply_removal(removal.plan_removal_lifecycle(tmp_path, ["headroom"]))
    assert result.status == "failed" and not result.removed_paths
    assert (tmp_path / removal.RUNTIMES["headroom"][0]).exists()


def test_interrupted_journal_blocks_new_plan(tmp_path):
    setup(tmp_path, ["headroom"])
    path = tmp_path / removal.JOURNALS
    path.mkdir()
    (path / "interrupted.json").write_text(
        json.dumps({"project_root": str(tmp_path), "status": "running"})
    )
    with pytest.raises(InstallerError, match="interrupted"):
        removal.plan_removal_lifecycle(tmp_path, ["headroom"])


def test_actual_read_growth_is_bounded(tmp_path, monkeypatch):
    path = tmp_path / "runtime"
    path.mkdir()
    (path / "file").write_text("x")
    monkeypatch.setattr(_removal_fs.os, "read", lambda *_: b"longer than original")
    with pytest.raises(InstallerError, match="grew"):
        _removal_fs.snapshot(str(tmp_path), "runtime")


def test_cli_plan_dry_run_apply_and_unknown_tool(tmp_path, capsys):
    setup(tmp_path, ["headroom"])
    assert main(["remove", "plan", str(tmp_path), "--tool", "headroom", "--json"]) == 0
    plan = tmp_path / "review.json"
    plan.write_text(capsys.readouterr().out)
    assert main(["remove", "apply", str(plan), "--dry-run", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"]
    assert main(["remove", "apply", str(plan), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["retired_tools"] == ["headroom"]
    with pytest.raises(SystemExit) as exc:
        main(["remove", "plan", str(tmp_path), "--tool", "unknown"])
    assert exc.value.code == 2


def test_partial_runtime_removal_continues_from_receipt_bound_release(tmp_path, monkeypatch):
    setup(tmp_path, ["playwright-mcp"])
    real = removal._removal_fs.remove_tree
    calls = []

    def fail_second(*args):
        calls.append(args[1])
        if len(calls) == 2:
            raise OSError("controlled failure")
        return real(*args)

    monkeypatch.setattr(removal._removal_fs, "remove_tree", fail_second)
    first = removal.apply_removal(removal.plan_removal_lifecycle(tmp_path, ["playwright-mcp"]))
    assert first.status == "failed" and len(first.removed_paths) == 1
    record = load_record(str(tmp_path))
    assert record.steps and len(record.runtime_releases) == 1
    monkeypatch.setattr(removal._removal_fs, "remove_tree", real)
    plan = removal.plan_removal_lifecycle(tmp_path, ["playwright-mcp"])
    assert [r.action for r in plan.runtimes] == ["released", "remove"]
    second = removal.apply_removal(plan)
    assert second.status == "succeeded" and second.retired_tools == ["playwright-mcp"]
    assert (tmp_path / removal.DATA["playwright-mcp"] / "reports/keep.json").exists()


def test_missing_runtime_without_release_never_retires_receipts(tmp_path):
    import shutil

    setup(tmp_path, ["headroom"])
    shutil.rmtree(tmp_path / removal.RUNTIMES["headroom"][0])
    result = removal.apply_removal(removal.plan_removal_lifecycle(tmp_path, ["headroom"]))
    assert not result.retired_tools
    assert load_record(str(tmp_path)).steps


def test_known_foreign_codex_registration_without_ownership_protects_runtime(tmp_path):
    setup(tmp_path, ["headroom"], configure=False)
    (tmp_path / ".codex").mkdir()
    value = (
        "[mcp_servers.foreign]"
        + chr(10)
        + "command = "
        + json.dumps(str(tmp_path / removal.RUNTIMES["headroom"][0] / "module"))
    )
    (tmp_path / ".codex/config.toml").write_text(value)
    plan = removal.plan_removal_lifecycle(tmp_path, ["headroom"])
    assert plan.runtimes[0].action == "retain"


def test_same_tool_retained_descendant_protects_runtime(tmp_path):
    record = setup(tmp_path, ["headroom"], configure=False)
    path = tmp_path / removal.RUNTIMES["headroom"][0] / "reports/user.json"
    path.parent.mkdir()
    path.write_text("retain")
    record.steps[0].owned_paths.append(str(path))
    _persist(record, project_root=str(tmp_path))
    assert removal.plan_removal_lifecycle(tmp_path, ["headroom"]).runtimes[0].action == "retain"


def test_infrastructure_receipt_does_not_authorize_runtime_deletion(tmp_path):
    record = setup(tmp_path, ["headroom"], configure=False)
    record.steps[0].owned_paths = [str(tmp_path / ".stackwinnow")]
    _persist(record, project_root=str(tmp_path))
    assert removal.plan_removal_lifecycle(tmp_path, ["headroom"]).runtimes[0].action == "retain"


def test_retained_directory_replacement_is_not_adopted(tmp_path):
    setup(tmp_path, ["headroom"])
    removal.apply_removal(removal.plan_removal_lifecycle(tmp_path, ["headroom"]))
    data = tmp_path / removal.DATA["headroom"]
    data.rename(tmp_path / "old-data")
    data.mkdir()
    assert not load_record(str(tmp_path)).retained_path("headroom", removal.DATA["headroom"])


def test_failed_configuration_cleanup_retains_original_and_releases_published_keys(
    tmp_path, monkeypatch
):
    from stackwinnow.contracts import OperationResult

    setup(tmp_path, ["headroom"])
    real = removal.apply_config_restore

    def fail_after(plan):
        result = real(plan)
        return result.model_copy(
            update={"result": OperationResult(status="failed", message="cleanup failed")}
        )

    monkeypatch.setattr(removal, "apply_config_restore", fail_after)
    result = removal.apply_removal(removal.plan_removal_lifecycle(tmp_path, ["headroom"]))
    assert result.status == "failed" and not result.removed_paths
    journal = json.loads((tmp_path / result.journal).read_text())
    assert journal["configuration_results"][0]["published"]
    assert journal["original_record"]["steps"][0]["configuration_ownership"]
    assert not load_record(str(tmp_path)).steps[0].configuration_ownership
    monkeypatch.setattr(removal, "apply_config_restore", real)
    assert removal.apply_removal(
        removal.plan_removal_lifecycle(tmp_path, ["headroom"])
    ).retired_tools == ["headroom"]


def test_fresh_plan_and_dry_run_for_empty_project_write_nothing(tmp_path):
    plan = removal.plan_removal_lifecycle(tmp_path, ["headroom"])
    assert removal.apply_removal(plan, dry_run=True).dry_run
    assert list(tmp_path.iterdir()) == []
    assert removal.apply_removal(plan).status == "skipped"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("kind", ["retained-alias", "evidence-report", "sibling-report"])
def test_playwright_subtrees_preserve_actual_retained_descendants(tmp_path, kind):
    from stackwinnow.contracts import EvidenceRef

    record = setup(tmp_path, ["playwright-mcp"], configure=False)
    node = tmp_path / removal.RUNTIMES["playwright-mcp"][0]
    state = tmp_path / removal.DATA["playwright-mcp"]
    record.steps[0].owned_paths = [str(state)]
    if kind == "retained-alias":
        outside = tmp_path / "external"
        outside.write_text("keep")
        alias = node / "keep-alias"
        alias.symlink_to(outside)
        record.steps[0].owned_paths.append(str(alias))
    else:
        report = (node if kind == "evidence-report" else state) / "reports/evidence.json"
        report.parent.mkdir(exist_ok=True)
        report.write_text("keep")
        record.steps[0].evidence = [EvidenceRef(source=str(report), detail="retained result")]
    _persist(record, project_root=str(tmp_path))
    plan = removal.plan_removal_lifecycle(tmp_path, ["playwright-mcp"])
    assert plan.runtimes[0].action == ("remove" if kind == "sibling-report" else "retain")

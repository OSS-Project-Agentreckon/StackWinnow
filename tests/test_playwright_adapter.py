import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from stackwinnow.adapters import playwright_mcp as adapter
from stackwinnow.adapters._managed import ManagedStateError
from stackwinnow.cli import main
from stackwinnow.installer import load_record
from stackwinnow.runner import CommandResult
from stackwinnow.verify import check_project, playwright_client


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setattr(adapter.shutil, "which", lambda name: "/runtime/" + name)
    monkeypatch.setattr(adapter.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(adapter.platform, "machine", lambda: "arm64")


class Runner:
    def __init__(self, root):
        self.root = root
        self.calls = []
        self.fail_install = False
        self.bad_integrity = False

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if args[-1] == "--version":
            return CommandResult(
                0, "v24.13.1" if args[0].endswith("node") else "codex-cli 0.169.0", ""
            )
        if args[0].endswith("npm"):
            if self.fail_install:
                return CommandResult(1, "", "install failed")
            modules = self.root / adapter.NODE / "node_modules"
            packages = {}
            for name, (version, integrity) in adapter.PACKAGES.items():
                package = modules / name
                package.mkdir(parents=True)
                (package / "package.json").write_text(
                    json.dumps({"name": name, "version": version, "license": "Apache-2.0"})
                )
                (package / "cli.js").write_text("// fixture")
                packages["node_modules/" + name] = {
                    "version": version,
                    "integrity": "wrong" if self.bad_integrity else integrity,
                }
            (modules / ".package-lock.json").write_text(json.dumps({"packages": packages}))
        elif "install" in args:
            binary = self.root / adapter.BROWSER
            binary.parent.mkdir(parents=True)
            binary.write_text("fixture executable")
            binary.chmod(0o700)
        else:
            raise AssertionError(args)
        return CommandResult(0, "", "")


@pytest.fixture
def client(monkeypatch):
    calls = []

    def run(root, registration, codex, **kwargs):
        calls.append((root, registration, codex))
        return {
            "connected": True,
            "functional": kwargs.get("scenario") != "fail",
            "message": "Fixture checked.",
            "evidence_path": str(root / "evidence.json"),
        }

    monkeypatch.setattr(playwright_client, "run_client_check", run)
    monkeypatch.setattr("stackwinnow.verify.playwright_mcp.run_client_check", run)
    return calls


def setup(root):
    runner = Runner(root)
    result = adapter.apply_playwright(
        adapter.plan_playwright(root, assistant="codex"), command_runner=runner
    )
    assert result.status == "succeeded", result.message
    return runner, result


def test_plan_and_dry_run_no_side_effects(tmp_path, runtime):
    plan = adapter.plan_playwright(tmp_path, assistant="codex")
    result = adapter.apply_playwright(
        plan, dry_run=True, command_runner=lambda *a, **kw: pytest.fail("command")
    )
    assert result.status == "skipped"
    assert not list(tmp_path.iterdir())
    assert plan.configuration.relative_path == ".codex/config.toml"
    assert plan.configuration.format == "toml"


def test_apply_repeat_and_preserve_unrelated_settings(tmp_path, runtime, client):
    parent = tmp_path / ".codex"
    parent.mkdir()
    config = parent / "config.toml"
    original = '# keep\n[mcp_servers.other]\ncommand = "unrelated"\n'
    config.write_text(original)
    runner, first = setup(tmp_path)
    assert len(client) == 1
    assert config.read_text().startswith(original)
    assert len(first.record.steps) == 3
    # Unrelated subsequent edits do not invalidate ownership of the server table.
    config.write_text("# another comment\n" + config.read_text())
    snapshot = config.read_bytes()
    runner.calls.clear()
    second = adapter.apply_playwright(
        adapter.plan_playwright(tmp_path, assistant="codex"), command_runner=runner
    )
    assert second.status == "succeeded"
    assert len(client) == 2
    assert len(runner.calls) == 2  # prerequisite version probes only
    assert config.read_bytes() == snapshot
    assert len(second.record.steps) == 6
    assert not second.record.steps[-2].configuration_ownership  # no false adoption
    assert adapter.inspect_setup(tmp_path, "/runtime/node") == (True, True)


def test_stale_plan_blocks_before_commands(tmp_path, runtime):
    plan = adapter.plan_playwright(tmp_path, assistant="codex")
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex/config.toml").write_text("# changed\n")
    runner = Runner(tmp_path)
    assert adapter.apply_playwright(plan, command_runner=runner).status == "blocked"
    assert not runner.calls


@pytest.mark.parametrize("failure", ["npm", "integrity"])
def test_install_failure_preserves_receipts_and_blocks_dependents(
    tmp_path, runtime, client, failure
):
    runner = Runner(tmp_path)
    runner.fail_install = failure == "npm"
    runner.bad_integrity = failure == "integrity"
    result = adapter.apply_playwright(
        adapter.plan_playwright(tmp_path, assistant="codex"), command_runner=runner
    )
    assert result.status == "failed"
    assert result.record.steps[0].owned_paths == [str(tmp_path / adapter.STATE)]
    assert not (tmp_path / ".codex").exists()
    assert not client
    assert len(runner.calls) == 3  # no browser package code before integrity validation
    with pytest.raises(ManagedStateError, match="incomplete"):
        adapter.plan_playwright(tmp_path, assistant="codex")


@pytest.mark.parametrize(
    "mutation", ["dry", "duplicate", "unowned", "config", "browser", "state-link"]
)
def test_invalid_setup_blocks_all_execution(tmp_path, runtime, client, mutation):
    runner, _ = setup(tmp_path)
    plan = adapter.plan_playwright(tmp_path, assistant="codex")
    path = tmp_path / ".stackwinnow/receipts.json"
    record = json.loads(path.read_text())
    if mutation == "dry":
        for step in record["steps"]:
            step["dry_run"] = True
    elif mutation == "duplicate":
        record["steps"].append(record["steps"][0])
    elif mutation == "unowned":
        record["steps"][1]["configuration_ownership"] = []
    elif mutation == "config":
        config = tmp_path / ".codex/config.toml"
        config.write_text(config.read_text().replace('"browser_click"', '"browser_type"'))
    elif mutation == "browser":
        (tmp_path / adapter.BROWSER).unlink()
    else:
        state = tmp_path / adapter.STATE
        state.rename(state.with_name("moved"))
        state.symlink_to(state.with_name("moved"), target_is_directory=True)
    path.write_text(json.dumps(record))
    runner.calls.clear()
    assert adapter.apply_playwright(plan, command_runner=runner).status == "blocked"
    report = check_project(
        tmp_path, tool_ids=["playwright-mcp"], run_functional=True, command_runner=runner
    )
    assert not report.ready
    assert not runner.calls
    assert len(client) == 1


def test_revalidation_under_lock(tmp_path, runtime, client, monkeypatch):
    runner, _ = setup(tmp_path)

    @contextmanager
    def changed_lock(root):
        path = root / ".stackwinnow/receipts.json"
        record = json.loads(path.read_text())
        record["steps"].append(record["steps"][0])
        path.write_text(json.dumps(record))
        yield

    monkeypatch.setattr(adapter, "operation_lock", changed_lock)
    result = adapter.apply_playwright(
        adapter.plan_playwright(tmp_path, assistant="codex"), command_runner=runner
    )
    assert result.status == "blocked"
    assert len(client) == 1


def test_read_only_and_fresh_checks(tmp_path, runtime, client):
    runner, _ = setup(tmp_path)
    runner.calls.clear()
    report = check_project(tmp_path, tool_ids=["playwright-mcp"], command_runner=runner)
    assert not report.ready
    assert [str(c.status) for c in report.tools[0].checks] == [
        "succeeded",
        "succeeded",
        "not_run",
        "not_run",
    ]
    assert not runner.calls
    report = check_project(
        tmp_path, tool_ids=["playwright-mcp"], run_functional=True, command_runner=runner
    )
    assert report.ready
    report = check_project(
        tmp_path,
        tool_ids=["playwright-mcp"],
        run_functional=True,
        scenario="fail",
        command_runner=runner,
    )
    assert not report.ready
    assert str(report.status) == "failed"


def test_cli_plan_and_dry_run(tmp_path, runtime, capsys):
    assert main(["playwright-mcp", "plan", str(tmp_path), "--assistant", "codex", "--json"]) == 0
    plan = tmp_path / "plan.json"
    plan.write_text(capsys.readouterr().out)
    assert main(["playwright-mcp", "apply", str(plan), "--dry-run", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "skipped"
    assert list(tmp_path.iterdir()) == [plan]


@pytest.mark.parametrize("kind", ["platform", "missing", "version"])
def test_runtime_block_leaves_project_unchanged(tmp_path, runtime, monkeypatch, kind):
    plan = adapter.plan_playwright(tmp_path, assistant="codex")
    runner = Runner(tmp_path)
    if kind == "platform":
        monkeypatch.setattr(adapter.platform, "system", lambda: "Linux")
    elif kind == "missing":
        monkeypatch.setattr(
            adapter.shutil, "which", lambda name: None if name == "codex" else "/runtime/" + name
        )
    else:

        def runner(*a, **kw):
            return CommandResult(0, "codex-cli 0.1.0", "")

    result = adapter.apply_playwright(plan, command_runner=runner)
    assert result.status == "blocked"
    assert not list(tmp_path.iterdir())


def test_matching_unowned_registration_not_adopted(tmp_path, runtime):
    from stackwinnow.configure.codex import apply_codex_server

    plan = adapter.plan_playwright(tmp_path, assistant="codex")
    (tmp_path / ".codex").mkdir()
    assert apply_codex_server(plan.configuration).result.status == "succeeded"
    with pytest.raises(ManagedStateError, match="without ownership"):
        adapter.plan_playwright(tmp_path, assistant="codex")


def test_failed_real_receipt_ownership_is_retained(tmp_path, runtime, client):
    runner, _ = setup(tmp_path)
    path = tmp_path / ".stackwinnow/receipts.json"
    record = json.loads(path.read_text())
    record["steps"][1]["status"] = "failed"
    path.write_text(json.dumps(record))
    report = check_project(
        tmp_path, tool_ids=["playwright-mcp"], run_functional=True, command_runner=runner
    )
    assert report.ready


@pytest.mark.parametrize("failure", ["directory", "npmrc", "npm", "browser"])
def test_install_exceptions_retain_created_state_ownership(
    tmp_path, runtime, client, monkeypatch, failure
):
    plan = adapter.plan_playwright(tmp_path, assistant="codex")
    runner = Runner(tmp_path)
    original_mkdir, original_open = Path.mkdir, Path.open

    def mkdir(path, *args, **kwargs):
        if failure == "directory" and path == tmp_path / adapter.STATE / "home":
            raise PermissionError("simulated child-directory failure")
        return original_mkdir(path, *args, **kwargs)

    def open_file(path, *args, **kwargs):
        if failure == "npmrc" and path == tmp_path / adapter.STATE / "global.npmrc":
            raise PermissionError("simulated npmrc creation failure")
        return original_open(path, *args, **kwargs)

    def commands(args, **kwargs):
        if (failure == "npm" and args[0].endswith("npm")) or (
            failure == "browser" and "chromium" in args
        ):
            raise PermissionError("simulated command launch failure")
        return runner(args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    monkeypatch.setattr(Path, "open", open_file)
    result = adapter.apply_playwright(plan, command_runner=commands)
    assert result.status == "failed", result.message
    record = load_record(str(tmp_path))
    receipt = record.receipt_for(plan.installation.steps[0].step_id)
    assert receipt.status == "failed"
    assert receipt.owned_paths == [str(tmp_path / adapter.STATE)]
    assert result.record == record
    assert not client and not (tmp_path / ".codex").exists()
    # Recovery still requires inspection, but the real partial write stays owned.
    with pytest.raises(ManagedStateError, match="incomplete"):
        adapter.plan_playwright(tmp_path, assistant="codex")


def test_failed_state_creation_does_not_adopt_a_competing_directory(
    tmp_path, runtime, client, monkeypatch
):
    plan = adapter.plan_playwright(tmp_path, assistant="codex")
    original = Path.mkdir
    state = tmp_path / adapter.STATE

    def racing_mkdir(path, *args, **kwargs):
        if path == state:
            original(path, *args, **kwargs)
            (state / "external.txt").write_text("belongs to another operation")
            raise FileExistsError("another operation created the directory")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", racing_mkdir)
    runner = Runner(tmp_path)
    result = adapter.apply_playwright(plan, command_runner=runner)
    assert result.status == "failed"
    receipt = load_record(str(tmp_path)).receipt_for(plan.installation.steps[0].step_id)
    assert receipt.owned_paths == []
    assert list(state.iterdir()) == [state / "external.txt"]
    assert len(runner.calls) == 2  # Only preflight probes, never npm or the browser.
    assert not client


@pytest.mark.parametrize("operation", ["apply", "check"])
@pytest.mark.parametrize("mutation", ["config", "missing-config", "browser", "ownership"])
def test_setup_changes_during_client_execution_block_readiness(
    tmp_path, runtime, client, monkeypatch, operation, mutation
):
    runner, _ = setup(tmp_path)
    config = tmp_path / ".codex/config.toml"
    modified = []

    def changed_client(root, registration, codex, **kwargs):
        assert (root / ".stackwinnow/playwright-mcp.lock").exists()
        if mutation == "config":
            config.write_text(config.read_text().replace('"browser_click"', '"browser_type"'))
        elif mutation == "missing-config":
            config.unlink()
        elif mutation == "browser":
            (root / adapter.BROWSER).unlink()
        else:
            path = root / ".stackwinnow/receipts.json"
            record = json.loads(path.read_text())
            for receipt in record["steps"]:
                receipt["owned_paths"] = []
            path.write_text(json.dumps(record))
        modified.append(config.read_bytes() if config.exists() else None)
        return {
            "connected": True,
            "functional": True,
            "message": "Isolated client passed.",
            "evidence_path": str(root / "evidence.json"),
        }

    monkeypatch.setattr(playwright_client, "run_client_check", changed_client)
    monkeypatch.setattr("stackwinnow.verify.playwright_mcp.run_client_check", changed_client)
    if operation == "apply":
        result = adapter.apply_playwright(
            adapter.plan_playwright(tmp_path, assistant="codex"), command_runner=runner
        )
        assert result.status == "blocked"
        receipt = load_record(str(tmp_path)).receipt_for(result.plan.installation.steps[-1].step_id)
        assert receipt.status != "succeeded"
    else:
        report = check_project(
            tmp_path, tool_ids=["playwright-mcp"], run_functional=True, command_runner=runner
        )
        assert not report.ready and report.status == "blocked"
    assert modified == [config.read_bytes() if config.exists() else None]


@pytest.mark.parametrize("operation", ["apply", "check"])
def test_unrelated_config_edits_during_client_check_are_preserved(
    tmp_path, runtime, client, monkeypatch, operation
):
    runner, _ = setup(tmp_path)
    config = tmp_path / ".codex/config.toml"
    expected = b"# user comment during check\n" + config.read_bytes()

    def changed_client(root, registration, codex, **kwargs):
        config.write_bytes(expected)
        return {
            "connected": True,
            "functional": True,
            "message": "Client passed.",
            "evidence_path": str(root / "evidence.json"),
        }

    monkeypatch.setattr(playwright_client, "run_client_check", changed_client)
    monkeypatch.setattr("stackwinnow.verify.playwright_mcp.run_client_check", changed_client)
    if operation == "apply":
        result = adapter.apply_playwright(
            adapter.plan_playwright(tmp_path, assistant="codex"), command_runner=runner
        )
        assert result.status == "succeeded"
    else:
        assert check_project(
            tmp_path, tool_ids=["playwright-mcp"], run_functional=True, command_runner=runner
        ).ready
    assert config.read_bytes() == expected

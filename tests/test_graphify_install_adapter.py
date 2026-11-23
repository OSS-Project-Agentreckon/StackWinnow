"""Install-only Graphify ownership, stale-plan, repeat and failure acceptance."""

import json
import sys
from pathlib import Path

import pytest

from stackwinnow.adapters import graphify_install as adapter
from stackwinnow.adapters import graphify_plan as preparation
from stackwinnow.adapters.graphify import GraphifyError, RelationshipExpectation
from stackwinnow.cli import main
from stackwinnow.installer import ExecutionRecord, StepReceipt
from stackwinnow.runner import CommandResult
from stackwinnow.state.lock import project_lock


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project with spaces"
    root.mkdir()
    (root / "caller.py").write_text("from callee import answer\ndef call(): return answer()\n")
    (root / "callee.py").write_text("def answer(): return 42\n")
    runtime = preparation.RuntimeSnapshot(
        executable=sys.executable,
        implementation="CPython",
        version="3.11.14",
        system="Darwin",
        machine="arm64",
        macos_version="14.0",
    )
    monkeypatch.setattr(preparation, "_runtime", lambda: runtime)
    return root


@pytest.fixture
def plan(project):
    return preparation.plan_graphify_execution(
        project,
        expectation=RelationshipExpectation(
            caller_file="caller.py",
            caller_label="call()",
            callee_file="callee.py",
            callee_label="answer()",
        ),
    )


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_historical_client_advisory_preserves_reviewed_install_identity(project, plan):
    legacy = plan.model_copy(
        update={
            "blockers": tuple(
                preparation._OLD_CLIENT_ADVISORY if b == preparation._CLIENT_ADVISORY else b
                for b in plan.blockers
            )
        }
    )
    assert preparation.validate_graphify_execution_plan(legacy) == legacy
    runner = FakeInstall()
    assert adapter.apply_graphify_install(legacy, command_runner=runner).installed
    assert adapter.apply_graphify_install(legacy, command_runner=runner).installed
    assert len(runner.calls) == 4
    assert adapter.validate_graphify_installation(project)[0] == legacy


class FakeInstall:
    def __init__(self, *, fail=None, raises=False, mutation=None):
        self.calls = []
        self.fail = fail
        self.raises = raises
        self.mutation = mutation

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        root = Path(kwargs["cwd"])
        if self.fail == len(self.calls):
            if self.raises:
                raise OSError("simulated subprocess failure")
            return CommandResult(1, "", "controlled failure")
        if len(self.calls) == 1:
            python = root / preparation.ENV_PATH / "bin/python"
            python.parent.mkdir(parents=True)
            python.write_text("fake Python; runner contract only, no real installation claim")
        if len(self.calls) == 4 and self.mutation:
            self.mutation(root)
        return CommandResult(0, "Graphify locked environment verified.", "")


def test_dry_run_has_no_commands_network_or_files(project, plan, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("dry run must be offline")

    monkeypatch.setattr("subprocess.Popen", forbidden)
    before = snapshot(project)
    result = adapter.apply_graphify_install(plan, dry_run=True, command_runner=forbidden)
    assert not result.installed and not result.ready and result.dry_run
    assert snapshot(project) == before
    assert not (project / ".stackwinnow").exists()


def test_install_repeat_and_serialized_plan_preserve_other_files(project, plan, tmp_path):
    (project / ".codex").mkdir()
    (project / ".codex/config.toml").write_text("# owned by user\n")
    before = snapshot(project)
    runner = FakeInstall()
    result = adapter.apply_graphify_install(plan, command_runner=runner)
    assert result.installed and not result.ready and result.scope == "local-install-only"
    receipt = result.record.receipt_for(adapter.STEP_ID)
    assert receipt.owned_paths == [adapter.INSTALL_ROOT]
    assert receipt.evidence and receipt.status == "succeeded"
    assert not (project / ".stackwinnow/graphify").exists()
    assert all((project / path).read_bytes() == raw for path, raw in before.items())
    argv, options = runner.calls[2]
    assert {
        "--require-hashes",
        "--no-index",
        "--no-deps",
        "--no-cache-dir",
        "--only-binary=:all:",
    } <= set(argv)
    assert all(call[0][1] == "-I" for call in runner.calls)
    assert Path(options["extra_env"]["HOME"]).is_relative_to(project / adapter.INSTALL_ROOT)
    after = snapshot(project)
    saved = tmp_path / "plan.json"
    saved.write_text(plan.model_dump_json())
    checked = adapter.load_graphify_install_plan(saved)
    repeat = adapter.apply_graphify_install(checked, command_runner=runner)
    assert repeat.installed and repeat.results[0].status == "skipped"
    assert len(runner.calls) == 4 and after == snapshot(project)


def test_installation_manifest_does_not_prevent_runtime_removal(project, plan):
    from stackwinnow.runtime.remove import plan_removal

    adapter.apply_graphify_install(plan, command_runner=FakeInstall())
    before = snapshot(project)
    removal = plan_removal(str(project.resolve()), ["graphify"])

    assert [item.path for item in removal.candidates] == [adapter.INSTALL_ROOT]
    assert snapshot(project) == before


@pytest.mark.parametrize("phase", [1, 2, 3, 4])
@pytest.mark.parametrize("raises", [False, True])
def test_failures_retain_partial_ownership_and_block_retry(project, plan, phase, raises):
    runner = FakeInstall(fail=phase, raises=raises)
    result = adapter.apply_graphify_install(plan, command_runner=runner)
    assert not result.installed
    assert result.record.receipt_for(adapter.STEP_ID).owned_paths == [adapter.INSTALL_ROOT]
    assert result.results[0].status == "failed"
    assert len(runner.calls) == phase
    before = snapshot(project)
    with pytest.raises(GraphifyError, match="manual inspection"):
        adapter.apply_graphify_install(plan, command_runner=runner)
    assert snapshot(project) == before and len(runner.calls) == phase


@pytest.mark.parametrize(
    "change", ["source", "recipe", "runtime", "receipt", "unowned", "symlink", "occupied-step"]
)
def test_invalid_inputs_block_before_mutation(project, plan, change, tmp_path, monkeypatch):
    if change == "source":
        (project / "callee.py").write_text("def answer(): return 7\n")
    elif change == "recipe":
        plan = plan.model_copy(update={"operations": ("run-arbitrary-command",)})
    elif change == "runtime":
        monkeypatch.setattr(
            preparation, "_runtime", lambda: plan.runtime.model_copy(update={"version": "3.14.0"})
        )
    elif change in ("receipt", "occupied-step"):
        (project / ".stackwinnow").mkdir()
        record = ExecutionRecord(project_root=str(project))
        if change == "occupied-step":
            record.steps.append(
                StepReceipt(
                    step_id=adapter.STEP_ID,
                    tool_id="promptfoo",
                    status="succeeded",
                    message="other tool",
                    timestamp="now",
                )
            )
        (project / ".stackwinnow/receipts.json").write_text(record.model_dump_json())
    elif change == "unowned":
        (project / adapter.INSTALL_ROOT).mkdir(parents=True)
    else:
        (project / ".stackwinnow").symlink_to(tmp_path / "outside", target_is_directory=True)
    before = snapshot(project)
    runner = FakeInstall()
    with pytest.raises(GraphifyError):
        adapter.apply_graphify_install(plan, command_runner=runner)
    assert not runner.calls and snapshot(project) == before


@pytest.mark.parametrize(
    "change", ["edited", "missing", "extra", "link", "manifest", "receipt", "permissions"]
)
def test_changed_installation_is_not_silently_reused(project, plan, change):
    runner = FakeInstall()
    adapter.apply_graphify_install(plan, command_runner=runner)
    binary = project / preparation.ENV_PATH / "bin/python"
    if change == "edited":
        binary.write_text("changed")
    elif change == "missing":
        binary.unlink()
    elif change == "extra":
        (binary.parent / "unrecognized").write_text("new file")
    elif change == "link":
        binary.unlink()
        binary.symlink_to(project / "caller.py")
    elif change == "manifest":
        (project / adapter.MANIFEST).write_text("{}")
    elif change == "permissions":
        binary.chmod(0o700)
    else:
        receipt_file = project / ".stackwinnow/receipts.json"
        record = ExecutionRecord.model_validate_json(receipt_file.read_text())
        record.steps[0].owned_paths = ["."]
        receipt_file.write_text(record.model_dump_json())
    before = snapshot(project)
    with pytest.raises(GraphifyError):
        adapter.apply_graphify_install(plan, command_runner=runner)
    assert snapshot(project) == before and len(runner.calls) == 4


def test_source_change_during_execution_records_failure(project, plan):
    runner = FakeInstall(mutation=lambda root: (root / "caller.py").write_text("changed\n"))
    result = adapter.apply_graphify_install(plan, command_runner=runner)
    assert not result.installed and result.results[0].status == "failed"
    assert result.record.receipt_for(adapter.STEP_ID).owned_paths == [adapter.INSTALL_ROOT]
    assert not (project / adapter.MANIFEST).exists()


def test_second_operation_cannot_write_receipts(project, plan):
    runner = FakeInstall()
    with project_lock(project):
        with pytest.raises(GraphifyError, match="Another StackWinnow operation"):
            adapter.apply_graphify_install(plan, command_runner=runner)
        assert not runner.calls and not (project / ".stackwinnow/receipts.json").exists()


def test_validation_is_repeated_under_lock_before_receipt_write(project, plan, monkeypatch):
    real_validate = adapter._validate
    calls = 0

    def validate(candidate):
        nonlocal calls
        calls += 1
        if calls == 2:
            assert (project / ".stackwinnow/operation.lock").exists()
            (project / "callee.py").write_text("changed after preflight")
        return real_validate(candidate)

    monkeypatch.setattr(adapter, "_validate", validate)
    runner = FakeInstall()
    with pytest.raises(GraphifyError, match="inputs changed"):
        adapter.apply_graphify_install(plan, command_runner=runner)
    assert not runner.calls and not (project / ".stackwinnow").exists()


def test_competing_directory_is_never_adopted(project, plan, monkeypatch):
    mkdir = Path.mkdir

    def race(path, *args, **kwargs):
        if path == project / adapter.INSTALL_ROOT:
            mkdir(path)
        return mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", race)
    runner = FakeInstall()
    result = adapter.apply_graphify_install(plan, command_runner=runner)
    assert not result.installed and not runner.calls
    assert result.record.receipt_for(adapter.STEP_ID).owned_paths == []


def test_cli_requires_explicit_install_scope_and_reports_dry_run(project, plan, tmp_path, capsys):
    saved = tmp_path / "plan.json"
    saved.write_text(plan.model_dump_json())
    with pytest.raises(SystemExit) as error:
        main(["graphify", "apply", str(saved)])
    assert error.value.code == 2
    capsys.readouterr()
    assert main(["graphify", "apply", str(saved), "--install-only", "--dry-run", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["dry_run"] and result["scope"] == "local-install-only"
    assert not result["installed"] and not result["ready"]
    assert not (project / ".stackwinnow").exists()


def test_other_tool_receipts_survive_install(project, plan):
    directory = project / ".stackwinnow"
    directory.mkdir()
    other = StepReceipt(
        step_id="promptfoo-install",
        tool_id="promptfoo",
        status="succeeded",
        message="Installed",
        timestamp="now",
    )
    record = ExecutionRecord(project_root=str(project), steps=[other])
    (directory / "receipts.json").write_text(record.model_dump_json())
    plan = preparation.plan_graphify_execution(project, expectation=plan.expectation)
    result = adapter.apply_graphify_install(plan, command_runner=FakeInstall())
    assert result.installed and result.record.receipt_for(other.step_id) == other


def test_unsupported_host_dry_run_blocks_even_if_plan_matches(project, plan, monkeypatch):
    monkeypatch.setattr(
        preparation, "_runtime", lambda: plan.runtime.model_copy(update={"system": "Linux"})
    )
    plan = preparation.plan_graphify_execution(project, expectation=plan.expectation)
    with pytest.raises(GraphifyError, match="requires CPython"):
        adapter.apply_graphify_install(plan, dry_run=True)
    assert not (project / ".stackwinnow").exists()


@pytest.mark.parametrize("failure", ["home", "requirements", "inventory", "manifest"])
def test_file_failures_after_creation_preserve_ownership(project, plan, monkeypatch, failure):
    original_mkdir = Path.mkdir
    original_open = Path.open

    def mkdir(path, *args, **kwargs):
        if failure == "home" and path == project / adapter.INSTALL_ROOT / "home":
            raise OSError("controlled directory failure")
        return original_mkdir(path, *args, **kwargs)

    def open_file(path, *args, **kwargs):
        if (failure == "requirements" and path.name == "requirements.txt") or (
            failure == "manifest" and path.name == "installation.json"
        ):
            raise OSError("controlled write failure")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    monkeypatch.setattr(Path, "open", open_file)
    if failure == "inventory":

        def fail_inventory(root):
            raise OSError("controlled inventory failure")

        monkeypatch.setattr(adapter, "_inventory", fail_inventory)
    result = adapter.apply_graphify_install(plan, command_runner=FakeInstall())
    assert not result.installed and result.results[0].status == "failed"
    assert result.record.receipt_for(adapter.STEP_ID).owned_paths == [adapter.INSTALL_ROOT]
    expected_phase = (
        "post-install-verification"
        if failure in ("inventory", "manifest")
        else "create-environment"
    )
    assert result.results[0].message == f"Graphify {expected_phase} could not complete (OSError)."


def test_unreadable_inventory_directory_blocks_reuse(project, plan, monkeypatch):
    runner = FakeInstall()
    adapter.apply_graphify_install(plan, command_runner=runner)

    def walk(path, *, followlinks, onerror):
        onerror(PermissionError("controlled inaccessible directory"))
        return []

    monkeypatch.setattr(adapter.os, "walk", walk)
    with pytest.raises(GraphifyError, match="Cannot inspect all"):
        adapter.apply_graphify_install(plan, command_runner=runner)
    assert len(runner.calls) == 4


@pytest.mark.parametrize("conflict", ["source", "unowned"])
def test_apply_preserves_actionable_graphify_validation_errors(project, plan, conflict):
    if conflict == "source":
        (project / "caller.py").write_text("changed source\n")
    else:
        (project / adapter.INSTALL_ROOT).mkdir(parents=True)
    with pytest.raises(GraphifyError) as original:
        adapter._validate(plan)
    runner = FakeInstall()
    with pytest.raises(GraphifyError) as reported:
        adapter.apply_graphify_install(plan, command_runner=runner)
    assert str(reported.value) == str(original.value)
    assert reported.value.__cause__ is None
    assert not runner.calls

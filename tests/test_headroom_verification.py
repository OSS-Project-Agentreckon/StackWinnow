"""Fresh shared verification, current ownership and retained Headroom project data."""

import json
from pathlib import Path

import pytest
from test_headroom_adapter import CommandResult, FakeCommands

from stackwinnow.adapters import headroom as adapter
from stackwinnow.adapters import headroom_state as state
from stackwinnow.installer import load_record
from stackwinnow.verify import check_project


@pytest.fixture(autouse=True)
def supported(monkeypatch):
    monkeypatch.setattr(adapter.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(adapter.platform, "machine", lambda: "arm64")


@pytest.fixture
def installed(tmp_path):
    result = adapter.apply_headroom(adapter.plan_headroom(tmp_path), command_runner=FakeCommands())
    assert result.status == "succeeded", result.message
    return tmp_path


def check(root, runner=None, **kwargs):
    return check_project(root, tool_ids=["headroom"], command_runner=runner, **kwargs)


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_passive_checks_never_execute_or_write(tmp_path, installed):
    before = snapshot(installed)
    runner = FakeCommands()
    report = check(installed, runner)
    assert not report.ready
    assert [c.status for c in report.tools[0].checks] == [
        "succeeded",
        "succeeded",
        "not_applicable",
        "not_run",
    ]
    assert snapshot(installed) == before
    assert runner.calls == []


def test_missing_install_blocks_without_creating_state(tmp_path):
    runner = FakeCommands()
    assert check(tmp_path, runner, run_functional=True).status == "blocked"
    assert not list(tmp_path.iterdir())
    assert runner.calls == []


def test_fresh_zero_savings_repeat_and_negative_control(installed):
    runner = FakeCommands()
    runner.compress_output = {"tokens_saved": 0, "tokens_after": 100}
    first = check(installed, runner, run_functional=True)
    second = check(installed, runner, run_functional=True)
    assert first.ready and second.ready
    first_path = first.tools[0].checks[-1].evidence[0].source
    second_path = second.tools[0].checks[-1].evidence[0].source
    assert first_path != second_path
    report = json.loads((installed / first_path).read_text())
    assert report["measurement"]["tokens_saved"] == 0
    assert not check(installed).ready
    negative = check(installed, runner, run_functional=True, scenario="fail")
    assert negative.status == "failed"
    assert "Negative control" in negative.tools[0].checks[-1].message
    assert len(runner.calls) == 3


@pytest.mark.parametrize(
    "overrides",
    [
        {"tokens_saved": True},
        {"tokens_before": "100"},
        {"tokens_after": -1},
        {"tokens_saved": 9},
        {"messages_in": 3},
        {"messages_out": 0},
        {"system_preserved": False},
        {"failure_preserved": False},
        {"run_id": "old-run"},
        {"tokenizer": "cl100k_base"},
    ],
)
def test_untrusted_counts_and_stale_or_incomplete_evidence_fail(installed, overrides):
    runner = FakeCommands()
    runner.compress_output = overrides
    report = check(installed, runner, run_functional=True)
    assert report.status == "failed"
    evidence = report.tools[0].checks[-1].evidence[0]
    data = json.loads((installed / evidence.source).read_text())
    assert data["status"] == "failed"
    assert "measurement" not in data


@pytest.mark.parametrize(
    "output", ['{"tokens_saved":1,"tokens_saved":2}', "[]", "NOT JSON", "x" * 70000]
)
def test_malformed_output_fails(installed, output):
    class Bad(FakeCommands):
        def __call__(self, *args, **kwargs):
            return CommandResult(stdout=output)

    assert check(installed, Bad(), run_functional=True).status == "failed"


@pytest.mark.parametrize("target", [state.ENV + "/bin/python", state.MANIFEST])
def test_runtime_tampering_blocks_before_execution(installed, target):
    (installed / target).write_text("changed")
    runner = FakeCommands()
    assert check(installed, runner, run_functional=True).status == "blocked"
    assert runner.calls == []


def test_runtime_change_during_command_invalidates_success(installed):
    class Mutates(FakeCommands):
        def __call__(self, *args, **kwargs):
            result = super().__call__(*args, **kwargs)
            (installed / state.ENV / "bin/python").write_text("changed")
            return result

    assert check(installed, Mutates(), run_functional=True).status == "failed"


@pytest.mark.parametrize("mutation", ["foreign", "duplicate", "dry-run", "failed", "digest"])
def test_invalid_receipts_cannot_establish_installation(installed, mutation):
    path = installed / ".stackwinnow/receipts.json"
    value = json.loads(path.read_text())
    if mutation == "foreign":
        value["project_root"] = str(installed.parent)
    elif mutation == "duplicate":
        value["steps"].append(value["steps"][0])
    elif mutation == "dry-run":
        value["steps"][0]["dry_run"] = True
    elif mutation == "failed":
        value["steps"][0]["status"] = "failed"
    else:
        value["steps"][0]["evidence"][0]["detail"] = "sha256:wrong"
    path.write_text(json.dumps(value))
    runner = FakeCommands()
    assert check(installed, runner, run_functional=True).status == "blocked"
    assert runner.calls == []


def test_cache_alias_blocks_and_external_file_survives(installed, tmp_path):
    target = tmp_path / "external"
    target.write_text("preserve me")
    (installed / state.CACHE / "alias").symlink_to(target)
    assert check(installed, FakeCommands(), run_functional=True).status == "blocked"
    assert target.read_text() == "preserve me"


def test_failed_install_retains_created_roots(tmp_path):
    runner = FakeCommands()
    runner.pip_exit = 1
    result = adapter.apply_headroom(adapter.plan_headroom(tmp_path), command_runner=runner)
    assert result.status == "failed"
    receipt = load_record(str(tmp_path)).steps[0]
    assert receipt.owned_paths == state.owned_paths(tmp_path)
    with pytest.raises(adapter.HeadroomError):
        adapter.plan_headroom(tmp_path)


def test_callbacks_hold_shared_lock_and_use_private_environment(installed):
    class Locked(FakeCommands):
        def __call__(self, args, *, cwd, timeout, extra_env=None):
            assert (Path(cwd) / ".stackwinnow/operation.lock").is_file()
            assert "-I" in args and "-B" in args
            assert extra_env["HOME"] == str(installed / state.STATE / "home")
            assert extra_env["TMPDIR"] == str(installed / state.STATE / "tmp")
            assert extra_env["PIP_CONFIG_FILE"] == "/dev/null"
            return super().__call__(args, cwd=cwd, timeout=timeout, extra_env=extra_env)

    assert check(installed, Locked(), run_functional=True).ready


def test_lock_contention_does_not_execute(installed):
    from stackwinnow.state.lock import project_lock

    runner = FakeCommands()
    with project_lock(installed):
        assert check(installed, runner, run_functional=True).status == "blocked"
    assert not runner.calls


def test_retention_includes_cache_before_any_compression_report(tmp_path):
    from stackwinnow.contracts import InstallPlan, PlanStep
    from stackwinnow.installer import RunnerOutcome, execute_plan
    from stackwinnow.runtime.remove import plan_removal

    (tmp_path / state.ENV).mkdir(parents=True)
    (tmp_path / state.CACHE).mkdir(parents=True)
    (tmp_path / state.CACHE / "vocabulary").write_text("cache")
    execute_plan(
        InstallPlan(
            project_root=str(tmp_path),
            tool_ids=["headroom"],
            steps=[
                PlanStep(
                    step_id="headroom-install", tool_id="headroom", description="Install runtime."
                )
            ],
        ),
        step_runner=lambda _: RunnerOutcome(
            status="succeeded", message="Installed.", owned_paths=state.owned_paths(tmp_path)
        ),
    )
    plan = plan_removal(str(tmp_path))
    assert {p.path for p in plan.candidates} == {str(tmp_path / state.ENV)}
    assert {p.path for p in plan.retained} == {state.STATE}


def test_revalidation_under_lock_rejects_changed_runtime(installed, monkeypatch):
    from stackwinnow.verify import headroom as verifier

    real_execute = verifier.execute_plan

    def change_then_execute(*args, **kwargs):
        (installed / state.ENV / "bin/python").write_text("changed after baseline")
        return real_execute(*args, **kwargs)

    monkeypatch.setattr(verifier, "execute_plan", change_then_execute)
    runner = FakeCommands()
    assert check(installed, runner, run_functional=True).status == "blocked"
    assert not runner.calls


def test_runner_exception_preserves_failed_install_ownership(tmp_path):
    class Broken(FakeCommands):
        def __call__(self, *args, **kwargs):
            raise RuntimeError("synthetic runner exception")

    result = adapter.apply_headroom(adapter.plan_headroom(tmp_path), command_runner=Broken())
    assert result.status == "failed"
    assert load_record(str(tmp_path)).steps[0].owned_paths == state.owned_paths(tmp_path)


def test_shared_cli_reports_readiness_and_dimensions(installed, monkeypatch, capsys):
    from stackwinnow.cli import main
    from stackwinnow.verify import headroom as verifier

    monkeypatch.setattr(verifier, "run_command", FakeCommands())
    assert main(["check", str(installed), "--tool", "headroom", "--json"]) == 1
    passive = json.loads(capsys.readouterr().out)
    assert not passive["ready"]
    assert main(["check", str(installed), "--tool", "headroom", "--run-functional", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ready"]


@pytest.mark.parametrize("mutation", ["system", "failure"])
def test_real_fixture_script_detects_changed_required_content(monkeypatch, capsys, mutation):
    import sys
    from types import ModuleType, SimpleNamespace

    module = ModuleType("headroom")

    def compress(messages, **kwargs):
        assert kwargs == {"model": "gpt-4o", "kompress_model": "disabled"}
        if mutation == "system":
            # Mutating in place must not change the original expected instruction.
            messages[0]["content"] = "An altered system instruction."
        else:
            messages[1]["content"] = "FAIL test_timeout: unrelated failure"
        return SimpleNamespace(
            messages=messages, tokens_before=100, tokens_after=90, tokens_saved=10
        )

    module.compress = compress
    tokenizer = ModuleType("tiktoken.model")
    tokenizer.encoding_name_for_model = lambda _: "o200k_base"
    monkeypatch.setitem(sys.modules, "headroom", module)
    monkeypatch.setitem(sys.modules, "tiktoken.model", tokenizer)
    exec(adapter._compress_script("fresh"), {})
    data = json.loads(capsys.readouterr().out)
    assert data[mutation + "_preserved"] is False
    with pytest.raises(ValueError):
        adapter.CompressionRun.model_validate(data)

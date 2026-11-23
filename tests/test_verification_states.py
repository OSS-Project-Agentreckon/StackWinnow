"""Verification must separate stored setup from freshly observed functionality."""

import json
import os
import shutil
from contextlib import contextmanager
from pathlib import Path

import pytest
from promptfoo_fakes import FakeCommands
from pydantic import ValidationError

from stackwinnow import cli
from stackwinnow.adapters import promptfoo as adapter
from stackwinnow.installer import load_record
from stackwinnow.plan import check_plan
from stackwinnow.verify import (
    CheckKind,
    ToolVerification,
    VerificationCheck,
    VerificationError,
    VerificationReport,
    check_project,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX project configuration")


@pytest.fixture
def commands(monkeypatch):
    monkeypatch.setattr(adapter.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(adapter.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(adapter.shutil, "which", lambda name: f"/declared/{name}")
    return FakeCommands()


@pytest.fixture
def onboard(tmp_path, commands, monkeypatch):
    def create(provider="deterministic"):
        root = tmp_path / f"{provider} project "
        root.mkdir()
        if provider == "openai":
            monkeypatch.setenv("OPENAI_API_KEY", "synthetic-verification-test-key")
        plan = adapter.plan_promptfoo(
            root, provider=provider, model="explicit-test-model" if provider == "openai" else None
        )
        result = adapter.apply_promptfoo(plan, allow_provider_usage=True, command_runner=commands)
        assert result.status == "succeeded", result.message
        return root.resolve()

    return create


def check(root, commands, **kwargs):
    return check_project(root, tool_ids=["promptfoo"], command_runner=commands, **kwargs)


def dimensions(report):
    return {item.kind.value: item for item in report.tools[0].checks}


def snapshot(root):
    return {
        str(path.relative_to(root)): (
            path.read_bytes(),
            path.stat().st_mode,
            path.stat().st_mtime_ns,
        )
        for path in root.rglob("*")
        if path.is_file()
    }


INVALID_RECEIPTS = (
    "dry-run-installation",
    "dry-run-runtime-state",
    "dry-run-configuration",
    "duplicate-step",
)


def invalidate_receipts(root, problem):
    path = root / ".stackwinnow/receipts.json"
    data = json.loads(path.read_text())
    if problem == "duplicate-step":
        data["steps"].append(data["steps"][0])
    elif problem == "dry-run-configuration":
        for step in data["steps"]:
            if step["configuration_ownership"]:
                step["dry_run"] = True
    else:
        relative = (
            adapter.NODE_PREFIX if problem == "dry-run-installation" else adapter.STATE_PREFIX
        )
        owned_path = str(root / relative)
        step = next(step for step in data["steps"] if owned_path in step["owned_paths"])
        # Leave the other resource owned by a real receipt so each gate is tested.
        step["owned_paths"].remove(owned_path)
        data["steps"].append(
            {
                **step,
                "step_id": step["step_id"] + "-dry-run",
                "dry_run": True,
                "owned_paths": [owned_path],
            }
        )
    path.write_text(json.dumps(data))
    return path.read_bytes()


def test_missing_setup_reports_independent_states_without_installing(tmp_path, commands):
    result = check(tmp_path, commands, run_functional=True)
    states = dimensions(result)
    assert states["installed"].code == "installation-missing"
    assert states["configured"].code == "configuration-missing"
    assert states["connected"].status == "not_applicable"
    assert states["functional"].status == "blocked"
    assert result.status == "failed" and not result.ready
    assert commands.calls == [] and list(tmp_path.iterdir()) == []


def test_read_only_check_never_reuses_old_functional_success(onboard, commands):
    root = onboard()
    before = snapshot(root)
    calls = list(commands.calls)
    result = check(root, commands)
    states = dimensions(result)
    assert states["installed"].status == states["configured"].status == "succeeded"
    assert states["functional"].status == "not_run" and not result.ready
    assert states["connected"].status == "not_applicable"
    assert commands.calls == calls and snapshot(root) == before
    assert result.project_root.endswith(" ")
    assert VerificationReport.model_validate_json(result.model_dump_json()) == result
    payload = result.as_payload()
    assert payload["ready"] is False and payload["tools"][0]["ready"] is False


def test_fresh_check_runs_only_evaluation_and_keeps_existing_configuration(onboard, commands):
    root = onboard()
    config = root / "promptfooconfig.stackwinnow.json"
    config_before = config.read_bytes(), config.stat().st_mtime_ns
    first = check(root, commands, run_functional=True)
    second = check(root, commands, run_functional=True)
    assert first.ready and second.ready
    assert first.tools[0].connection_scope == "standalone"
    assert commands.count("install") == 1 and commands.count("eval") == 3
    assert (config.read_bytes(), config.stat().st_mtime_ns) == config_before
    record = load_record(str(root))
    assert len(record.steps) == 5  # Three onboarding steps, then one evaluation per check.
    paths = [dimensions(report)["functional"].evidence[0].source for report in (first, second)]
    assert paths[0] != paths[1] and all(Path(path).is_file() for path in paths)
    assert all(step.step_id.endswith("-evaluate") for step in record.steps[-2:])
    assert len([patch for step in record.steps for patch in step.configuration_ownership]) == 1


def test_wrong_output_fails_functionality_without_changing_installation_state(onboard, commands):
    root = onboard()
    result = check(root, commands, run_functional=True, scenario="fail")
    states = dimensions(result)
    assert result.status == "failed" and not result.ready
    assert states["installed"].status == states["configured"].status == "succeeded"
    assert states["functional"].status == "failed"
    assert "0/2" in states["functional"].message
    assert load_record(str(root)).steps[-1].status == "failed"
    assert dimensions(check(root, commands))["functional"].status == "not_run"


def test_functional_check_does_not_require_npm(onboard, commands, monkeypatch):
    root = onboard()
    monkeypatch.setattr(
        adapter.shutil, "which", lambda name: "/declared/node" if name == "node" else None
    )
    assert check(root, commands, run_functional=True).ready
    assert commands.count("install") == 1


@pytest.mark.parametrize("part", ["installation", "configuration"])
def test_missing_owned_resource_is_reported_without_repair(onboard, commands, part):
    root = onboard()
    if part == "installation":
        shutil.rmtree(root / adapter.NODE_PREFIX)
    else:
        (root / "promptfooconfig.stackwinnow.json").unlink()
    before = snapshot(root)
    calls = list(commands.calls)
    result = check(root, commands, run_functional=True)
    assert not result.ready and dimensions(result)["functional"].status == "blocked"
    assert commands.calls == calls and snapshot(root) == before


@pytest.mark.parametrize("part", ["configuration", "mode", "package", "integrity"])
def test_changed_owned_resources_block_execution(onboard, commands, part):
    root = onboard()
    if part == "configuration":
        (root / "promptfooconfig.stackwinnow.json").write_text('{"private-sentinel":true}')
    elif part == "mode":
        (root / "promptfooconfig.stackwinnow.json").chmod(0o644)
    elif part == "package":
        path = root / adapter.NODE_PREFIX / "node_modules/promptfoo/package.json"
        path.write_text('{"name":"promptfoo","version":"0.1.0","license":"MIT"}')
    else:
        path = root / adapter.NODE_PREFIX / "node_modules/.package-lock.json"
        data = json.loads(path.read_text())
        data["packages"]["node_modules/promptfoo"]["integrity"] = "wrong"
        path.write_text(json.dumps(data))
    before, calls = snapshot(root), list(commands.calls)
    result = check(root, commands, run_functional=True)
    assert result.status == "failed"
    assert dimensions(result)["functional"].status == "blocked"
    assert "private-sentinel" not in result.model_dump_json()
    assert commands.calls == calls and snapshot(root) == before


def test_dry_run_receipts_never_supply_ownership(onboard, commands):
    root = onboard()
    path = root / ".stackwinnow/receipts.json"
    data = json.loads(path.read_text())
    for step in data["steps"]:
        step["dry_run"] = True
    path.write_text(json.dumps(data))
    result = check(root, commands, run_functional=True)
    assert dimensions(result)["installed"].code == "installation-unowned"
    assert dimensions(result)["configured"].code == "configuration-unowned"
    assert commands.count("eval") == 1


def test_dry_run_history_preserves_real_ownership_and_receipts(onboard, commands):
    root = onboard()
    path = root / ".stackwinnow/receipts.json"
    data = json.loads(path.read_text())
    preview = {
        **data["steps"][0],
        "step_id": data["steps"][0]["step_id"] + "-preview",
        "dry_run": True,
    }
    data["steps"].append(preview)
    path.write_text(json.dumps(data))
    before = load_record(str(root)).steps

    result = check(root, commands, run_functional=True)

    assert result.ready
    assert commands.count("install") == 1 and commands.count("eval") == 2
    assert load_record(str(root)).steps[:-1] == before


@pytest.mark.parametrize("provider", ["deterministic", "openai"])
@pytest.mark.parametrize("problem", INVALID_RECEIPTS)
def test_direct_evaluation_rejects_invalid_ownership_before_commands(
    onboard, commands, provider, problem
):
    root = onboard(provider)
    plan = adapter.plan_promptfoo(
        root, provider=provider, model="explicit-test-model" if provider == "openai" else None
    )
    invalidate_receipts(root, problem)
    before, calls = snapshot(root), list(commands.calls)
    evaluations = commands.count("eval")

    result = adapter.evaluate_existing_promptfoo(
        plan, allow_provider_usage=True, command_runner=commands
    )

    assert commands.count("eval") == evaluations
    assert commands.calls == calls
    assert result.status == "blocked" and result.evaluation is None
    assert snapshot(root) == before


@pytest.mark.parametrize(
    "relative", [".stackwinnow", ".stackwinnow/envs/promptfoo", ".stackwinnow/receipts.json"]
)
def test_unsafe_managed_paths_are_blocked_without_following_them(tmp_path, commands, relative):
    root, outside = tmp_path / "project", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / relative
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside)
    result = check(root, commands, run_functional=True)
    assert result.status == "blocked" and not result.ready
    assert commands.calls == [] and list(outside.iterdir()) == []


@pytest.mark.parametrize("problem", ["corrupt", "wrong-root", "oversized", "duplicate-step"])
def test_bad_receipts_produce_sanitized_blocked_results(onboard, commands, problem):
    root = onboard()
    path = root / ".stackwinnow/receipts.json"
    if problem == "corrupt":
        path.write_text('{"private-sentinel": true}')
    elif problem == "wrong-root":
        data = json.loads(path.read_text())
        data["project_root"] += "-elsewhere"
        path.write_text(json.dumps(data))
    elif problem == "duplicate-step":
        data = json.loads(path.read_text())
        data["steps"].append(data["steps"][0])
        path.write_text(json.dumps(data))
    else:
        with path.open("wb") as stream:
            stream.truncate(adapter.MAX_JSON_BYTES + 1)
    result = check(root, commands, run_functional=True)
    assert result.status == "blocked" and "private-sentinel" not in result.model_dump_json()
    assert commands.count("eval") == 1


@pytest.mark.parametrize("allowed,has_key", [(False, True), (True, False)])
def test_hosted_check_is_blocked_without_explicit_opt_in_and_credential(
    onboard, commands, monkeypatch, allowed, has_key
):
    root = onboard("openai")
    if not has_key:
        monkeypatch.delenv("OPENAI_API_KEY")
    calls, before = list(commands.calls), snapshot(root)
    result = check(
        root, commands, provider="openai", run_functional=True, allow_provider_usage=allowed
    )
    assert dimensions(result)["connected"].status == "blocked"
    assert dimensions(result)["functional"].status == "blocked"
    assert not result.ready and commands.calls == calls and snapshot(root) == before
    assert "synthetic-verification-test-key" not in result.model_dump_json()


def test_hosted_response_and_bad_assertions_are_distinct_with_command_double(onboard, commands):
    root = onboard("openai")

    def incorrect(report):
        report["results"]["stats"] = {"successes": 0, "failures": 2, "errors": 0}
        for row in report["results"]["results"]:
            row.update(success=False, response={"output": "incorrect answer"})
        return report

    commands.report_change = incorrect
    commands.eval_exit = 100
    result = check(
        root, commands, provider="openai", run_functional=True, allow_provider_usage=True
    )
    assert result.tools[0].connection_scope == "provider"
    assert dimensions(result)["connected"].status == "succeeded"
    assert dimensions(result)["functional"].status == "failed" and not result.ready
    for args, _, environment in commands.calls:
        if "eval" not in args:
            assert "OPENAI_API_KEY" not in environment


def test_hosted_read_only_check_does_not_claim_connectivity(onboard, commands, monkeypatch):
    root = onboard("openai")
    monkeypatch.delenv("OPENAI_API_KEY")
    calls = list(commands.calls)
    result = check(root, commands, provider="openai")
    assert dimensions(result)["connected"].status == "not_run"
    assert not result.ready and commands.calls == calls


def test_hosted_success_reports_provider_scope_with_command_double(onboard, commands):
    root = onboard("openai")
    result = check(
        root, commands, provider="openai", run_functional=True, allow_provider_usage=True
    )
    assert result.ready and result.tools[0].connection_scope == "provider"
    assert dimensions(result)["connected"].code == "provider-responded"
    assert "synthetic-verification-test-key" not in result.model_dump_json()


@pytest.mark.parametrize("problem", ["missing-node", "wrong-node", "runner", "lock"])
def test_unavailable_execution_is_blocked_without_changing_owned_setup(
    onboard, commands, monkeypatch, problem
):
    root = onboard()
    if problem == "missing-node":
        monkeypatch.setattr(adapter.shutil, "which", lambda name: None)
    elif problem == "wrong-node":
        commands.node_version = "v22.18.0\n"
    elif problem == "runner":
        monkeypatch.setattr(adapter, "_default_runner", lambda: None)
    else:
        (root / ".stackwinnow/promptfoo.lock").write_text("another operation")
    before = snapshot(root)
    result = check(root, None if problem == "runner" else commands, run_functional=True)
    states = dimensions(result)
    assert states["installed"].status == states["configured"].status == "succeeded"
    assert states["functional"].status == "blocked" and not result.ready
    assert commands.count("eval") == commands.count("install") == 1
    assert snapshot(root) == before


@pytest.mark.parametrize("problem", ["missing", "changed", "stale", "absent-summary"])
def test_invalid_returned_evidence_cannot_establish_fresh_success(
    onboard, commands, monkeypatch, problem
):
    root = onboard("openai")
    previous = next((root / adapter.STATE_PREFIX / "results").glob("*.json"))
    evaluate = adapter.evaluate_existing_promptfoo

    def interrupted(plan, **kwargs):
        outcome = evaluate(plan, **kwargs)
        assert outcome.status == "succeeded"
        if problem == "missing":
            Path(outcome.evaluation.result_path).unlink()
        elif problem == "changed":
            Path(outcome.evaluation.result_path).write_text("{}")
        elif problem == "stale":
            outcome.evaluation.result_path = str(previous)
        else:
            outcome.evaluation = None
        return outcome

    monkeypatch.setattr(adapter, "evaluate_existing_promptfoo", interrupted)
    result = check(
        root, commands, provider="openai", run_functional=True, allow_provider_usage=True
    )
    states = dimensions(result)
    assert states["functional"].status == "failed" and not result.ready
    assert states["connected"].status != "succeeded"
    if problem == "absent-summary":
        assert "No fresh evaluation" in states["functional"].message
    else:
        assert states["functional"].code == "evaluation-evidence-invalid"


def test_preflight_managed_state_does_not_establish_functional_readiness(onboard, commands):
    root = onboard()
    plan = adapter.plan_promptfoo(root)
    preflight = check_plan(plan.installation)
    assert preflight.is_ready_to_apply
    assert all(item.status == "skip-already-managed" for item in preflight.checks)
    assert not check(root, commands).ready
    (root / plan.configuration.relative_path).write_text('{"modified":true}')
    assert check_plan(plan.installation).is_ready_to_apply
    result = check(root, commands, run_functional=True)
    assert dimensions(result)["configured"].status == "failed" and not result.ready
    assert commands.count("eval") == 1


@pytest.mark.parametrize("problem", ["invalid-report", "timeout", "cli-version"])
def test_runtime_failures_cannot_reuse_previous_success(onboard, commands, problem):
    root = onboard()
    if problem == "invalid-report":
        commands.report_change = lambda report: {}
    elif problem == "timeout":
        commands.timed_out = True
    else:
        commands.tool_version = "0.0.0"
    result = check(root, commands, run_functional=True)
    assert not result.ready and dimensions(result)["functional"].status == "failed"
    assert commands.count("install") == 1


def test_change_during_version_probe_is_not_executed(onboard, commands):
    root = onboard()

    def changing_runner(args, **kwargs):
        result = commands(args, **kwargs)
        if len(args) == 3 and args[-1] == "--version":
            (root / "promptfooconfig.stackwinnow.json").write_text('{"user":"changed"}')
        return result

    result = check_project(
        root, tool_ids=["promptfoo"], run_functional=True, command_runner=changing_runner
    )
    assert not result.ready and dimensions(result)["configured"].status == "failed"
    assert commands.count("eval") == 1


def test_change_before_plan_creation_updates_the_report(onboard, commands, monkeypatch):
    root = onboard()
    create_plan = adapter.plan_promptfoo

    def changed_plan(*args, **kwargs):
        (root / "promptfooconfig.stackwinnow.json").write_text('{"user":"changed"}')
        return create_plan(*args, **kwargs)

    monkeypatch.setattr(adapter, "plan_promptfoo", changed_plan)
    result = check(root, commands, run_functional=True)
    assert dimensions(result)["configured"].status == "failed" and not result.ready
    assert commands.count("eval") == 1


def test_configuration_change_while_acquiring_lock_is_rechecked(onboard, commands, monkeypatch):
    root = onboard()
    original = adapter._operation_lock

    @contextmanager
    def changing_lock(project):
        with original(project):
            (root / "promptfooconfig.stackwinnow.json").write_text('{"user":"changed"}')
            yield

    monkeypatch.setattr(adapter, "_operation_lock", changing_lock)
    result = check(root, commands, run_functional=True)
    assert not result.ready and commands.count("eval") == 1
    assert not (root / ".stackwinnow/promptfoo.lock").exists()


@pytest.mark.parametrize("provider", ["deterministic", "openai"])
@pytest.mark.parametrize("problem", INVALID_RECEIPTS)
def test_invalid_receipts_acquired_under_lock_block_before_tool_commands(
    onboard, commands, monkeypatch, provider, problem
):
    root = onboard(provider)
    original = adapter._operation_lock
    changed = []
    calls = len(commands.calls)
    evaluations = commands.count("eval")
    reports = set((root / adapter.STATE_PREFIX / "results").iterdir())

    @contextmanager
    def changing_lock(project):
        with original(project):
            changed.append(invalidate_receipts(root, problem))
            yield

    monkeypatch.setattr(adapter, "_operation_lock", changing_lock)
    result = check(
        root, commands, provider=provider, run_functional=True, allow_provider_usage=True
    )

    assert commands.count("eval") == evaluations
    assert [args for args, _, _ in commands.calls[calls:]] == [["/declared/node", "--version"]]
    assert not result.ready and dimensions(result)["functional"].status == "blocked"
    if provider == "openai":
        assert dimensions(result)["connected"].status == "blocked"
    assert changed == [(root / ".stackwinnow/receipts.json").read_bytes()]
    assert set((root / adapter.STATE_PREFIX / "results").iterdir()) == reports
    assert not (root / ".stackwinnow/promptfoo.lock").exists()


@pytest.mark.parametrize("provider", ["deterministic", "openai"])
@pytest.mark.parametrize("problem", INVALID_RECEIPTS)
def test_receipt_change_during_cli_probe_blocks_before_evaluation(
    onboard, commands, provider, problem
):
    root = onboard(provider)
    evaluations = commands.count("eval")
    reports = set((root / adapter.STATE_PREFIX / "results").iterdir())
    changed = []

    def changing_runner(args, **kwargs):
        result = commands(args, **kwargs)
        if len(args) == 3 and args[-1] == "--version":
            changed.append(invalidate_receipts(root, problem))
        return result

    result = check(
        root,
        changing_runner,
        provider=provider,
        run_functional=True,
        allow_provider_usage=True,
    )

    assert commands.count("eval") == evaluations
    assert not result.ready and dimensions(result)["functional"].status == "blocked"
    assert changed == [(root / ".stackwinnow/receipts.json").read_bytes()]
    assert set((root / adapter.STATE_PREFIX / "results").iterdir()) == reports
    assert not (root / ".stackwinnow/promptfoo.lock").exists()


def test_check_on_unsupported_tool_never_calls_the_runner(tmp_path, commands):
    report = check_project(
        tmp_path, tool_ids=["aider"], run_functional=True, command_runner=commands
    )
    assert report.status == "blocked" and not report.ready
    assert all(check.code == "verifier-unavailable" for check in report.tools[0].checks)
    assert commands.calls == [] and list(tmp_path.iterdir()) == []


def test_one_working_tool_does_not_make_other_selected_tools_ready(onboard, commands):
    root = onboard()
    result = check_project(
        root, tool_ids=["promptfoo", "graphify"], run_functional=True, command_runner=commands
    )
    assert result.tools[0].ready and not result.tools[1].ready
    assert not result.ready and result.status == "blocked"


@pytest.mark.parametrize(
    "options",
    [
        {"tool_ids": []},
        {"tool_ids": ["promptfoo", "promptfoo"]},
        {"tool_ids": ["not-a-known-tool"]},
        {"tool_ids": "promptfoo"},
        {"tool_ids": ["promptfoo"], "scenario": "fail"},
        {"tool_ids": ["promptfoo"], "run_functional": 1},
    ],
)
def test_invalid_selections_are_input_errors(tmp_path, options):
    with pytest.raises(VerificationError):
        check_project(tmp_path, **options)
    assert list(tmp_path.iterdir()) == []


def test_model_requires_all_dimensions_and_rejects_na_functionality():
    with pytest.raises(ValidationError):
        ToolVerification(tool_id="promptfoo", connection_scope="standalone", checks=[])
    with pytest.raises(ValidationError):
        VerificationCheck(
            kind=CheckKind.FUNCTIONAL,
            status="not_applicable",
            code="invalid",
            message="Not measured.",
        )
    with pytest.raises(ValidationError, match="requires evidence"):
        VerificationCheck(
            kind=CheckKind.INSTALLED, status="succeeded", code="invalid", message="No evidence."
        )


def test_report_rejects_false_scope_duplicate_tools_and_cached_success(onboard, commands):
    root = onboard()
    report = check(root, commands, run_functional=True)
    original = report.model_dump()
    original["tools"][0]["connection_scope"] = "assistant"
    with pytest.raises(ValidationError, match="Only a standalone"):
        VerificationReport.model_validate(original)
    original = report.model_dump()
    original["tools"] = (original["tools"][0], original["tools"][0])
    with pytest.raises(ValidationError, match="must be unique"):
        VerificationReport.model_validate(original)
    original = report.model_dump()
    original["run_functional"] = False
    with pytest.raises(ValidationError, match="requires an executed check"):
        VerificationReport.model_validate(original)


def test_cli_reports_structured_and_human_states_and_exit_codes(
    onboard, commands, monkeypatch, capsys
):
    root = onboard()
    monkeypatch.setattr(adapter, "_default_runner", lambda: commands)
    args = ["check", str(root), "--tool", "promptfoo"]
    assert cli.main(args + ["--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["schema_version"] == 1 and data["ready"] is False
    assert data["status"] == "not_run"
    assert cli.main(args + ["--run-functional"]) == 0
    text = capsys.readouterr().out
    assert "ready: yes" in text and "[not_applicable] connected" in text
    assert cli.main(args + ["--run-functional", "--scenario", "fail", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
    with pytest.raises(SystemExit) as raised:
        cli.main(["check", str(root), "--tool", "unknown-tool", "--json"])
    assert raised.value.code == 2


def test_direct_evaluation_api_does_not_onboard_empty_project(tmp_path, commands):
    plan = adapter.plan_promptfoo(tmp_path)
    result = adapter.evaluate_existing_promptfoo(plan, command_runner=commands)
    assert result.status == "blocked" and commands.calls == []
    assert list(tmp_path.iterdir()) == []

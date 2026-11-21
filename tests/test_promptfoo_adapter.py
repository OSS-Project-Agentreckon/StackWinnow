"""Offline adapter checks; the command double never installs or calls a provider."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from promptfoo_fakes import FakeCommands
from pydantic import ValidationError

from stackwinnow.adapters import promptfoo as adapter
from stackwinnow.cli import main
from stackwinnow.contracts import ConfigApplyResult, OperationResult
from stackwinnow.installer import load_record

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX configuration writer")


@pytest.fixture
def commands(monkeypatch: pytest.MonkeyPatch) -> FakeCommands:
    monkeypatch.setattr(adapter.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(adapter.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(adapter.shutil, "which", lambda name: f"/declared/{name}")
    return FakeCommands()


def test_plan_roundtrip_and_dry_run_have_no_side_effects(tmp_path, commands):
    plan = adapter.plan_promptfoo(tmp_path)
    saved = tmp_path / "reviewed plan.json"
    saved.write_text(plan.model_dump_json())
    restored = adapter.load_promptfoo_plan(saved)
    assert restored == plan
    assert len(plan.installation.steps) == 3
    assert not plan.configuration.expected_file.exists
    result = adapter.apply_promptfoo(restored, dry_run=True, command_runner=commands)
    assert result.status == "skipped" and result.dry_run
    assert len(result.results) == 3
    assert commands.calls == []
    assert list(tmp_path.iterdir()) == [saved]


def test_missing_shared_runner_blocks_before_commands_or_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "_default_runner", lambda: None)
    result = adapter.apply_promptfoo(adapter.plan_promptfoo(tmp_path))
    assert result.status == "blocked"
    assert "shared command runner" in result.message
    assert list(tmp_path.iterdir()) == []


def test_install_configure_evaluate_and_ownership(tmp_path, commands):
    untouched = tmp_path / "package.json"
    untouched.write_bytes(b'{"private":true}\n')
    settings = tmp_path / "assistant-settings.json"
    settings.write_bytes(b'{"theme":"keep"}\n')
    plan = adapter.plan_promptfoo(tmp_path)
    result = adapter.apply_promptfoo(plan, command_runner=commands)
    assert result.status == "succeeded", result.message
    assert [item.status for item in result.results] == ["succeeded"] * 3
    assert result.evaluation.successes == 2
    assert result.evaluation.process_returncode == 0
    record = load_record(plan.project_root)
    config_receipt = record.receipt_for(plan.installation.steps[1].step_id)
    assert config_receipt.configuration_intents == [plan.configuration]
    assert config_receipt.configuration_ownership == [plan.configuration]
    assert record.steps[-1].evidence == result.results[-1].evidence
    assert Path(record.steps[-1].evidence[0].source).is_file()
    assert untouched.read_bytes() == b'{"private":true}\n'
    assert settings.read_bytes() == b'{"theme":"keep"}\n'
    assert not (tmp_path / ".stackwinnow/promptfoo.lock").exists()
    assert (tmp_path / ".stackwinnow/receipts.json").stat().st_mode & 0o777 == 0o600


def test_negative_control_records_failure_and_preserves_owned_config(tmp_path, commands):
    plan = adapter.plan_promptfoo(tmp_path, scenario="fail")
    result = adapter.apply_promptfoo(plan, command_runner=commands)
    assert result.status == "failed"
    assert result.evaluation.failures == 2 and result.evaluation.errors == 0
    assert result.evaluation.process_returncode == 100
    assert result.record.steps[-1].status == "failed"
    assert result.record.steps[1].configuration_ownership
    config = json.loads((tmp_path / plan.configuration.relative_path).read_text())
    assert config["defaultTest"]["vars"]["stackwinnowFail"] == "false"


def test_new_run_reuses_installation_and_configuration_but_evaluates_again(tmp_path, commands):
    first = adapter.apply_promptfoo(adapter.plan_promptfoo(tmp_path), command_runner=commands)
    original_bytes = (tmp_path / first.plan.configuration.relative_path).read_bytes()
    repeated = adapter.apply_promptfoo(first.plan, command_runner=commands)
    assert repeated.status == "blocked" and "already attempted" in repeated.message
    second = adapter.apply_promptfoo(adapter.plan_promptfoo(tmp_path), command_runner=commands)
    assert second.status == "succeeded", second.message
    assert commands.count("install") == 1 and commands.count("eval") == 2
    assert second.results[1].status == "skipped"
    assert second.evaluation.result_path != first.evaluation.result_path
    assert (tmp_path / first.plan.configuration.relative_path).read_bytes() == original_bytes
    ownership = [
        patch for receipt in second.record.steps for patch in receipt.configuration_ownership
    ]
    assert ownership == [first.plan.configuration]


@pytest.mark.parametrize("field", ["integrity", "provider_sha256", "description", "config-path"])
def test_modified_saved_plan_is_not_executable(tmp_path, commands, field):
    plan = adapter.plan_promptfoo(tmp_path)
    data = plan.model_dump(mode="json")
    if field == "description":
        data["installation"]["steps"][0]["description"] = "Different operation"
    elif field == "config-path":
        data["configuration"]["relative_path"] = "unrelated.json"
    else:
        data[field] = "0" * 64
    altered = adapter.PromptfooPlan.model_validate(data)
    assert adapter.apply_promptfoo(altered, command_runner=commands).status == "blocked"
    assert commands.calls == [] and list(tmp_path.iterdir()) == []


def test_new_file_after_preview_is_preserved(tmp_path, commands):
    plan = adapter.plan_promptfoo(tmp_path)
    config = tmp_path / plan.configuration.relative_path
    config.write_bytes(b'{"keep":true}')
    result = adapter.apply_promptfoo(plan, command_runner=commands)
    assert result.status == "blocked" and commands.calls == []
    assert config.read_bytes() == b'{"keep":true}'
    assert not (tmp_path / ".stackwinnow").exists()


@pytest.mark.parametrize("change", ["contents", "mode"])
def test_user_changes_to_owned_configuration_block_rerun(tmp_path, commands, change):
    first = adapter.apply_promptfoo(adapter.plan_promptfoo(tmp_path), command_runner=commands)
    path = tmp_path / first.plan.configuration.relative_path
    if change == "contents":
        path.write_text('{"user":"edited"}')
    else:
        path.chmod(0o644)
    before = path.read_bytes(), path.stat().st_mode
    with pytest.raises(adapter.PromptfooError, match="configuration changed"):
        adapter.plan_promptfoo(tmp_path)
    assert (path.read_bytes(), path.stat().st_mode) == before


@pytest.mark.parametrize(
    "relative",
    [
        ".stackwinnow",
        ".stackwinnow/envs",
        adapter.NODE_PREFIX,
        adapter.STATE_PREFIX + "/home",
        adapter.STATE_PREFIX + "/results",
    ],
)
def test_managed_directory_symlinks_are_rejected(tmp_path, relative):
    root = tmp_path / "project"
    outside = tmp_path / "unrelated"
    root.mkdir()
    outside.mkdir()
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(outside, target_is_directory=True)
    with pytest.raises(adapter.PromptfooError, match="real directories"):
        adapter.plan_promptfoo(root)
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("relative", [adapter.NODE_PREFIX, adapter.STATE_PREFIX])
def test_unowned_existing_directories_are_not_adopted(tmp_path, relative):
    (tmp_path / relative).mkdir(parents=True)
    with pytest.raises(adapter.PromptfooError, match="ownership receipt"):
        adapter.plan_promptfoo(tmp_path)


def test_root_redirection_after_preview_is_blocked(tmp_path, commands):
    root = tmp_path / "selected"
    root.mkdir()
    plan = adapter.plan_promptfoo(root)
    root.rename(tmp_path / "moved")
    root.symlink_to(tmp_path / "moved", target_is_directory=True)
    assert adapter.apply_promptfoo(plan, command_runner=commands).status == "blocked"
    assert commands.calls == [] and list((tmp_path / "moved").iterdir()) == []


def test_exact_project_path_with_trailing_space_survives_receipts(tmp_path, commands):
    root = tmp_path / "project with trailing space "
    root.mkdir()
    result = adapter.apply_promptfoo(adapter.plan_promptfoo(root), command_runner=commands)
    assert result.status == "succeeded", result.message
    assert result.plan.project_root == result.record.project_root == str(root.resolve())
    assert load_record(str(root.resolve())).project_root.endswith(" ")
    assert not root.with_name(root.name.rstrip()).exists()


@pytest.mark.parametrize("version", ["v22.22.0", "v24", "v24.1", "v24.1.2-extra", "not Node"])
def test_unsupported_or_malformed_node_version_blocks_without_writes(tmp_path, commands, version):
    commands.node_version = version
    result = adapter.apply_promptfoo(adapter.plan_promptfoo(tmp_path), command_runner=commands)
    assert result.status == "blocked" and "Node 24" in result.message
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("missing", ["node", "npm"])
def test_missing_prerequisite_blocks_before_commands(tmp_path, commands, monkeypatch, missing):
    monkeypatch.setattr(
        adapter.shutil, "which", lambda name: None if name == missing else f"/declared/{name}"
    )
    assert (
        adapter.apply_promptfoo(adapter.plan_promptfoo(tmp_path), command_runner=commands).status
        == "blocked"
    )
    assert commands.calls == [] and list(tmp_path.iterdir()) == []


def test_unverified_platform_blocks_execution_but_allows_preview(tmp_path, commands, monkeypatch):
    monkeypatch.setattr(adapter.platform, "system", lambda: "Linux")
    plan = adapter.plan_promptfoo(tmp_path)
    assert adapter.apply_promptfoo(plan, dry_run=True).status == "skipped"
    assert adapter.apply_promptfoo(plan, command_runner=commands).status == "blocked"
    assert commands.calls == [] and list(tmp_path.iterdir()) == []


def test_install_failure_keeps_receipts_and_stops_before_configuration(tmp_path, commands):
    commands.install_exit = 1
    result = adapter.apply_promptfoo(adapter.plan_promptfoo(tmp_path), command_runner=commands)
    assert [item.status for item in result.results] == ["failed", "skipped", "skipped"]
    assert not (tmp_path / result.plan.configuration.relative_path).exists()
    assert result.record.steps[0].owned_paths
    with pytest.raises(adapter.PromptfooError, match="incomplete or changed"):
        adapter.plan_promptfoo(tmp_path)


def test_cli_version_mismatch_is_not_success(tmp_path, commands):
    commands.tool_version = "0.1.0"
    result = adapter.apply_promptfoo(adapter.plan_promptfoo(tmp_path), command_runner=commands)
    assert result.status == "failed" and commands.count("eval") == 0
    assert not (tmp_path / result.plan.configuration.relative_path).exists()


@pytest.mark.parametrize("change", ["integrity", "license", "missing-entrypoint"])
def test_changed_owned_installation_is_not_reused(tmp_path, commands, change):
    result = adapter.apply_promptfoo(adapter.plan_promptfoo(tmp_path), command_runner=commands)
    assert result.status == "succeeded"
    prefix = tmp_path / adapter.NODE_PREFIX
    if change == "missing-entrypoint":
        (prefix / "node_modules/promptfoo/dist/src/entrypoint.js").unlink()
    elif change == "license":
        path = prefix / "node_modules/promptfoo/package.json"
        data = json.loads(path.read_text())
        data["license"] = "Proprietary"
        path.write_text(json.dumps(data))
    else:
        path = prefix / "node_modules/.package-lock.json"
        data = json.loads(path.read_text())
        data["packages"]["node_modules/promptfoo"]["integrity"] = "different"
        path.write_text(json.dumps(data))
    with pytest.raises(adapter.PromptfooError, match="incomplete or changed"):
        adapter.plan_promptfoo(tmp_path)
    assert commands.count("install") == 1


@pytest.mark.parametrize(
    "change",
    ["version", "missing-row", "duplicate-index", "wrong-output", "false-totals", "boolean-total"],
)
def test_invalid_report_never_records_success(tmp_path, commands, change):
    def alter(report):
        results = report["results"]
        if change == "version":
            results["version"] = 2
        elif change == "missing-row":
            results["results"].pop()
        elif change == "duplicate-index":
            results["results"][1]["testIdx"] = 0
        elif change == "wrong-output":
            results["results"][0]["response"]["output"] = "WRONG"
        elif change == "false-totals":
            results["results"][0]["success"] = False
        else:
            results["stats"]["errors"] = False
        return report

    commands.report_change = alter
    result = adapter.apply_promptfoo(adapter.plan_promptfoo(tmp_path), command_runner=commands)
    assert result.status == "failed" and result.evaluation is None
    assert result.record.steps[-1].status == "failed"
    diagnostic = {
        "version": "invalid results",
        "missing-row": "two expected cases",
        "duplicate-index": "identify the expected test cases",
        "wrong-output": "unexpected output",
        "false-totals": "totals disagree",
        "boolean-total": "invalid totals",
    }[change]
    assert diagnostic in result.message
    assert result.record.steps[-1].message == result.message


@pytest.mark.parametrize("failure", ["exit-code", "timeout"])
def test_success_report_does_not_override_process_failure(tmp_path, commands, failure):
    if failure == "exit-code":
        commands.eval_exit = 100
    else:
        commands.timed_out = True
    result = adapter.apply_promptfoo(adapter.plan_promptfoo(tmp_path), command_runner=commands)
    assert result.status == "failed" and result.evaluation.successes == 2


def test_unexpected_negative_control_pass_is_rejected(tmp_path, commands):
    def fake_pass(report):
        report["results"]["stats"] = {"successes": 2, "failures": 0, "errors": 0}
        for row, output in zip(report["results"]["results"], ["HELLO", "WORLD"], strict=True):
            row.update(success=True, response={"output": output})
        return report

    commands.report_change = fake_pass
    commands.eval_exit = 0
    result = adapter.apply_promptfoo(
        adapter.plan_promptfoo(tmp_path, scenario="fail"), command_runner=commands
    )
    assert result.status == "failed" and "unexpectedly passed" in result.message


@pytest.mark.parametrize(
    "options",
    [
        {"provider": "openai"},
        {"provider": "openai", "model": "bad/model"},
        {"provider": "openai", "model": "explicit-model", "scenario": "fail"},
        {"model": "unexpected"},
    ],
)
def test_provider_selection_requires_explicit_valid_model(tmp_path, options):
    with pytest.raises(ValidationError):
        adapter.plan_promptfoo(tmp_path, **options)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("allowed,key", [(False, "synthetic-key"), (True, None)])
def test_hosted_execution_needs_both_opt_in_and_key(tmp_path, commands, monkeypatch, allowed, key):
    if key:
        monkeypatch.setenv("OPENAI_API_KEY", key)
    else:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    plan = adapter.plan_promptfoo(tmp_path, provider="openai", model="explicit-model")
    result = adapter.apply_promptfoo(plan, allow_provider_usage=allowed, command_runner=commands)
    assert result.status == "blocked"
    assert commands.calls == [] and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("provider", ["deterministic", "openai"])
def test_credentials_only_reach_explicit_hosted_evaluation(
    tmp_path, commands, monkeypatch, provider
):
    # This is an environment-routing test with a fake command, never a provider call.
    secret = "synthetic-unit-test-credential"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setenv("UNRELATED_TOKEN", "must-not-forward")
    plan = adapter.plan_promptfoo(
        tmp_path, provider=provider, model="explicit-model" if provider == "openai" else None
    )
    result = adapter.apply_promptfoo(plan, allow_provider_usage=True, command_runner=commands)
    assert result.status == "succeeded"
    for args, cwd, env in commands.calls:
        hosted_eval = provider == "openai" and "eval" in args
        assert env.get("OPENAI_API_KEY") == (secret if hosted_eval else None)
        assert "UNRELATED_TOKEN" not in env
        assert secret not in str(args)
        assert env["DOTENV_CONFIG_PATH"] == str(tmp_path / adapter.STATE_PREFIX / "empty.env")
        assert env["PROMPTFOO_DISABLE_TELEMETRY"] == "1"
        if "eval" in args:
            assert cwd == tmp_path / adapter.STATE_PREFIX / "work"
            assert {"--no-write", "--no-cache", "--no-share", "--env-file"} <= set(args)
    assert secret not in result.model_dump_json()
    assert secret not in (tmp_path / ".stackwinnow/receipts.json").read_text()


def test_configuration_cleanup_failure_keeps_ownership_and_stops_evaluation(
    tmp_path, commands, monkeypatch
):
    real_apply = adapter.apply_json_edits

    def publish_then_fail(patch):
        applied = real_apply(patch)
        assert applied.ownership is not None
        return ConfigApplyResult(
            result=OperationResult(status="failed", message="Published; cleanup failed."),
            ownership=applied.ownership,
        )

    monkeypatch.setattr(adapter, "apply_json_edits", publish_then_fail)
    result = adapter.apply_promptfoo(adapter.plan_promptfoo(tmp_path), command_runner=commands)
    assert result.status == "failed" and commands.count("eval") == 0
    assert result.record.steps[-1].configuration_ownership == [result.plan.configuration]
    assert (tmp_path / result.plan.configuration.relative_path).exists()
    plan = adapter.plan_promptfoo(tmp_path)
    assert not plan.configuration.edits
    verification = adapter.evaluate_existing_promptfoo(plan, command_runner=commands)
    assert verification.status == "succeeded"
    assert commands.count("install") == commands.count("eval") == 1
    assert verification.record.steps[-2] == result.record.steps[-1]


@pytest.mark.parametrize(
    "raw", [b'{"run_id": 1, "run_id": 2}', b'{"n":NaN}', b'{"n":1e999}', b"[]", b"\xff"]
)
def test_plan_loader_rejects_ambiguous_or_invalid_json(tmp_path, raw):
    path = tmp_path / "bad.json"
    path.write_bytes(raw)
    with pytest.raises(adapter.PromptfooError):
        adapter.load_promptfoo_plan(path)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "large"])
def test_plan_loader_bounds_and_refuses_linked_files(tmp_path, kind):
    path = tmp_path / "plan.json"
    original = tmp_path / "original.json"
    original.write_text("{}")
    if kind == "symlink":
        path.symlink_to(original)
    elif kind == "hardlink":
        path.hardlink_to(original)
    else:
        with path.open("wb") as stream:
            stream.truncate(adapter.MAX_JSON_BYTES + 1)
    with pytest.raises(adapter.PromptfooError):
        adapter.load_promptfoo_plan(path)


def test_cli_plan_dry_run_and_missing_runner_json(tmp_path, capsys, monkeypatch):
    assert main(["promptfoo", "plan", str(tmp_path), "--json"]) == 0
    raw = capsys.readouterr().out
    saved = tmp_path / "plan.json"
    saved.write_text(raw)
    assert json.loads(raw)["version"] == adapter.VERSION
    assert main(["promptfoo", "apply", str(saved), "--dry-run", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "skipped"
    monkeypatch.setattr(adapter, "_default_runner", lambda: None)
    assert main(["promptfoo", "apply", str(saved), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"
    assert not (tmp_path / ".stackwinnow").exists()


def test_cli_invalid_plan_gives_sanitized_error(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text('{"unexpected":"private-input-sentinel"}')
    with pytest.raises(SystemExit) as raised:
        main(["promptfoo", "apply", str(path), "--json"])
    assert raised.value.code == 2
    captured = capsys.readouterr()
    assert "private-input-sentinel" not in captured.err and "Traceback" not in captured.err


def test_existing_operation_lock_is_preserved(tmp_path, commands):
    plan = adapter.plan_promptfoo(tmp_path)
    lock = tmp_path / ".stackwinnow/promptfoo.lock"
    lock.parent.mkdir()
    lock.write_bytes(b"another operation")
    result = adapter.apply_promptfoo(plan, command_runner=commands)
    assert result.status == "blocked" and "lock" in result.message
    assert lock.read_bytes() == b"another operation"
    assert commands.count("install") == 0
    assert not (lock.parent / "receipts.json").exists()


def test_new_valid_prefix_during_preflight_is_not_adopted(tmp_path, commands):
    plan = adapter.plan_promptfoo(tmp_path)
    prefix = tmp_path / adapter.NODE_PREFIX

    def racing_runner(args, **kwargs):
        if args == ["/declared/node", "--version"]:
            prefix.mkdir(parents=True)
            commands(
                [
                    "/declared/npm",
                    "install",
                    "--prefix",
                    str(prefix),
                    "--save-exact",
                    "--ignore-scripts",
                    "--no-audit",
                    "--no-fund",
                    "promptfoo@0.125.1",
                ],
                **kwargs,
            )
        return commands(args, **kwargs)

    result = adapter.apply_promptfoo(plan, command_runner=racing_runner)
    assert result.status == "blocked" and "ownership receipt" in result.message
    assert commands.count("install") == 1  # Only the simulated other installation.
    assert commands.count("eval") == 0
    assert load_record(plan.project_root).steps == []
    assert not (tmp_path / ".stackwinnow/promptfoo.lock").exists()
    assert not (tmp_path / plan.configuration.relative_path).exists()


def test_receipt_corruption_blocks_without_overwriting_it(tmp_path, commands):
    plan = adapter.plan_promptfoo(tmp_path)
    path = tmp_path / ".stackwinnow/receipts.json"
    path.parent.mkdir()
    path.write_bytes(b"keep corrupt receipt for recovery")
    result = adapter.apply_promptfoo(plan, command_runner=commands)
    assert result.status == "blocked" and "recovery" in result.message
    assert path.read_bytes() == b"keep corrupt receipt for recovery"
    assert commands.calls == []


def test_preexisting_result_is_never_overwritten_or_accepted(tmp_path, commands):
    first = adapter.apply_promptfoo(adapter.plan_promptfoo(tmp_path), command_runner=commands)
    plan = adapter.plan_promptfoo(tmp_path)
    path = tmp_path / adapter.STATE_PREFIX / "results" / f"{plan.run_id}.json"
    path.write_bytes(Path(first.evaluation.result_path).read_bytes())
    saved = path.read_bytes()
    result = adapter.apply_promptfoo(plan, command_runner=commands)
    assert result.status == "blocked" and result.evaluation is None
    assert path.read_bytes() == saved and commands.count("eval") == 1


def test_overlapping_apply_rechecks_receipts_under_lock(tmp_path, commands):
    plan = adapter.plan_promptfoo(tmp_path)
    completed = []

    def delayed_runner(args, **kwargs):
        if args == ["/declared/node", "--version"]:
            completed.append(adapter.apply_promptfoo(plan, command_runner=commands))
        return commands(args, **kwargs)

    delayed = adapter.apply_promptfoo(plan, command_runner=delayed_runner)
    assert completed[0].status == "succeeded"
    assert delayed.status == "blocked" and "already attempted" in delayed.message
    assert delayed.evaluation is None and delayed.results == []
    assert commands.count("install") == commands.count("eval") == 1
    assert load_record(plan.project_root) == completed[0].record
    assert not (tmp_path / ".stackwinnow/promptfoo.lock").exists()


def test_configuration_changed_during_preflight_blocks_before_receipts(tmp_path, commands):
    first = adapter.apply_promptfoo(adapter.plan_promptfoo(tmp_path), command_runner=commands)
    plan = adapter.plan_promptfoo(tmp_path)
    config = tmp_path / plan.configuration.relative_path
    receipts = tmp_path / ".stackwinnow/receipts.json"
    before = receipts.read_bytes()

    def change_configuration(args, **kwargs):
        if args == ["/declared/node", "--version"]:
            config.write_text('{"user":"keep changed configuration"}')
        return commands(args, **kwargs)

    result = adapter.apply_promptfoo(plan, command_runner=change_configuration)
    assert first.status == "succeeded" and result.status == "blocked"
    assert receipts.read_bytes() == before
    assert commands.count("eval") == 1
    assert not (tmp_path / ".stackwinnow/promptfoo.lock").exists()


def test_success_requires_a_fresh_evaluation(tmp_path, commands, monkeypatch):
    plan = adapter.plan_promptfoo(tmp_path)

    def skip_steps(installation, **kwargs):
        return load_record(installation.project_root), [
            OperationResult(status="skipped", message="Already completed.", step_id=step.step_id)
            for step in installation.steps
        ]

    monkeypatch.setattr(adapter, "execute_plan", skip_steps)
    result = adapter.apply_promptfoo(plan, command_runner=commands)
    assert result.status == "blocked" and result.evaluation is None
    assert "fresh" in result.message
    assert commands.count("eval") == 0
    assert not (tmp_path / ".stackwinnow/promptfoo.lock").exists()


def test_lock_close_failure_does_not_orphan_lock(tmp_path, commands, monkeypatch):
    plan = adapter.plan_promptfoo(tmp_path)
    lock = tmp_path / ".stackwinnow/promptfoo.lock"
    real_open, real_close = os.open, os.close
    lock_descriptor = None
    failed = False

    def capture_lock(path, *args, **kwargs):
        nonlocal lock_descriptor
        descriptor = real_open(path, *args, **kwargs)
        if path == lock:
            lock_descriptor = descriptor
        return descriptor

    def fail_lock_close(descriptor):
        nonlocal failed
        real_close(descriptor)
        if descriptor == lock_descriptor and not failed:
            failed = True
            raise OSError("simulated lock close failure")

    with monkeypatch.context() as changes:
        changes.setattr(os, "open", capture_lock)
        changes.setattr(os, "close", fail_lock_close)
        result = adapter.apply_promptfoo(plan, command_runner=commands)
    assert failed and result.status == "blocked"
    assert not lock.exists() and commands.count("install") == 0
    assert adapter.apply_promptfoo(plan, command_runner=commands).status == "succeeded"


def test_configuration_read_rejects_symlink_swapped_after_lstat(tmp_path, commands, monkeypatch):
    first = adapter.apply_promptfoo(adapter.plan_promptfoo(tmp_path), command_runner=commands)
    config = tmp_path / first.plan.configuration.relative_path
    outside = tmp_path / "unowned.json"
    outside.write_bytes(config.read_bytes())
    outside.chmod(config.stat().st_mode & 0o777)
    original_check = adapter._regular_file

    def swap_after_check(path, **kwargs):
        original_check(path, **kwargs)
        if path == config:
            path.unlink()
            path.symlink_to(outside)

    monkeypatch.setattr(adapter, "_regular_file", swap_after_check)
    with pytest.raises((adapter.PromptfooError, OSError)):
        adapter._check_existing_configuration(
            tmp_path, first.record, first.plan.configuration.relative_path
        )
    assert config.is_symlink()


def test_configuration_ownership_history_checks_the_latest_write(tmp_path, commands):
    first = adapter.apply_promptfoo(adapter.plan_promptfoo(tmp_path), command_runner=commands)
    from stackwinnow.contracts import JsonConfigEdit

    patch = adapter.plan_json_edits(
        tmp_path,
        first.plan.configuration.relative_path,
        tool_id="promptfoo",
        edits=[JsonConfigEdit(key_path=("description",), value="updated", replace_existing=True)],
    )
    outcome = adapter.apply_json_edits(patch)
    assert outcome.result.status == "succeeded"
    receipt = first.record.receipt_for(first.plan.installation.steps[1].step_id)
    receipt.configuration_ownership.append(outcome.ownership)
    adapter._check_existing_configuration(
        tmp_path, first.record, first.plan.configuration.relative_path
    )


def test_json_reader_cannot_hang_when_regular_file_is_replaced_by_fifo(tmp_path, subprocess_env):
    script = """
import os
import sys
from pathlib import Path
from stackwinnow.adapters import promptfoo as adapter
path = Path(sys.argv[1])
path.write_text('{}')
original_check = adapter._regular_file
def swap_after_check(candidate, **kwargs):
    original_check(candidate, **kwargs)
    candidate.unlink()
    os.mkfifo(candidate)
adapter._regular_file = swap_after_check
try:
    adapter._read_json(path)
except adapter.PromptfooError:
    pass
else:
    raise AssertionError('A replaced FIFO must be rejected')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "plan.json")],
        cwd=tmp_path,
        env={**subprocess_env, "PYTHONPATH": str(Path(adapter.__file__).resolve().parents[2])},
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("entrypoint", ["plan", "apply", "cli"])
def test_missing_promptfoo_catalog_entry_is_a_typed_error(
    tmp_path, commands, monkeypatch, capsys, entrypoint
):
    plan = adapter.plan_promptfoo(tmp_path)
    catalog = adapter.load_catalog()
    catalog._by_id.pop("promptfoo")
    monkeypatch.setattr(adapter, "load_catalog", lambda: catalog)
    if entrypoint == "plan":
        with pytest.raises(adapter.PromptfooError, match="not in the tool catalog"):
            adapter.plan_promptfoo(tmp_path)
    elif entrypoint == "apply":
        result = adapter.apply_promptfoo(plan, command_runner=commands)
        assert result.status == "blocked" and "not in the tool catalog" in result.message
    else:
        with pytest.raises(SystemExit) as raised:
            main(["promptfoo", "plan", str(tmp_path), "--json"])
        assert raised.value.code == 2
        assert "not in the tool catalog" in capsys.readouterr().err
    assert commands.calls == [] and list(tmp_path.iterdir()) == []

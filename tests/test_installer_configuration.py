"""Exercise durable configuration intent and ownership across executor failures."""

from __future__ import annotations

import hashlib
import json
import os

import pytest
from pydantic import ValidationError

from stackwinnow import installer
from stackwinnow.configure import apply_json_edits, plan_json_edits
from stackwinnow.contracts import EvidenceRef, InstallPlan, JsonConfigEdit

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX configuration writer")


@pytest.fixture
def configuration(tmp_path):
    root = str(tmp_path.resolve())
    patch = plan_json_edits(
        root,
        "settings.json",
        tool_id="promptfoo",
        edits=[JsonConfigEdit(key_path=("enabled",), value=True)],
    )
    plan = InstallPlan(
        project_root=root,
        tool_ids=["promptfoo"],
        steps=[
            {
                "step_id": "configure-promptfoo",
                "tool_id": "promptfoo",
                "description": "Apply owned configuration",
            }
        ],
    )
    return plan, patch


def test_intent_is_on_disk_before_configuration_and_ownership_after(configuration):
    plan, patch = configuration
    step_id = plan.steps[0].step_id
    evidence = EvidenceRef(source=patch.relative_path, detail="Owned setting was published.")

    def run(step):
        persisted = installer.load_record(plan.project_root).receipt_for(step_id)
        assert persisted.configuration_intents == [patch]
        assert not persisted.configuration_ownership
        assert persisted.status == "failed"
        applied = apply_json_edits(patch)
        return installer.RunnerOutcome(
            status=applied.result.status,
            message=applied.result.message,
            configuration_ownership=[applied.ownership],
            evidence=[evidence],
        )

    record, results = installer.execute_plan(
        plan, step_runner=run, configuration_intents={step_id: [patch]}
    )
    assert installer.load_record(plan.project_root) == record
    assert record.steps[0].configuration_ownership == [patch]
    assert record.steps[0].evidence == results[0].evidence == [evidence]


@pytest.mark.parametrize("mismatch", ["step", "tool", "project"])
def test_invalid_configuration_intent_is_rejected_before_side_effects(
    tmp_path, configuration, mismatch
):
    plan, patch = configuration
    step_id = plan.steps[0].step_id
    if mismatch == "step":
        step_id = "unknown-step"
    elif mismatch == "tool":
        patch = patch.model_copy(update={"tool_id": "headroom"})
    else:
        patch = patch.model_copy(update={"project_root": str(tmp_path / "other")})
    with pytest.raises(installer.InstallerError):
        installer.execute_plan(plan, configuration_intents={step_id: [patch]})
    assert list(tmp_path.iterdir()) == []


def test_configuration_intent_does_not_make_dry_run_write(tmp_path, configuration):
    plan, patch = configuration
    record, results = installer.execute_plan(
        plan,
        dry_run=True,
        configuration_intents={plan.steps[0].step_id: [patch]},
    )
    assert record.steps == [] and results[0].status == "skipped"
    assert list(tmp_path.iterdir()) == []


def test_failure_to_persist_intent_prevents_configuration(tmp_path, configuration, monkeypatch):
    plan, patch = configuration
    called = []

    def fail(record, *, project_root):
        raise OSError("simulated storage failure")

    monkeypatch.setattr(installer, "_persist", fail)
    with pytest.raises(OSError):
        installer.execute_plan(
            plan,
            step_runner=lambda step: called.append(step),
            configuration_intents={plan.steps[0].step_id: [patch]},
        )
    assert called == [] and list(tmp_path.iterdir()) == []


def test_receipt_write_failure_after_publication_retains_recovery_intent(
    tmp_path, configuration, monkeypatch
):
    plan, patch = configuration
    original = installer._persist
    writes = 0

    def fail_second(record, *, project_root):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("simulated disk failure after config publication")
        original(record, project_root=project_root)

    def run(step):
        result = apply_json_edits(patch)
        assert result.result.status == "succeeded"
        return installer.RunnerOutcome(
            status="succeeded", message="Published.", configuration_ownership=[result.ownership]
        )

    monkeypatch.setattr(installer, "_persist", fail_second)
    with pytest.raises(OSError):
        installer.execute_plan(
            plan, step_runner=run, configuration_intents={plan.steps[0].step_id: [patch]}
        )
    saved = installer.load_record(plan.project_root).steps[0]
    assert saved.status == "failed" and saved.configuration_ownership == []
    assert saved.configuration_intents == [patch]
    assert (
        hashlib.sha256((tmp_path / patch.relative_path).read_bytes()).hexdigest()
        == patch.written_file.sha256
    )


def test_old_receipts_load_with_empty_configuration_fields(tmp_path, configuration):
    plan, _ = configuration
    installer.execute_plan(plan)
    path = tmp_path / ".stackwinnow/receipts.json"
    data = json.loads(path.read_text())
    for step in data["steps"]:
        for key in ("configuration_intents", "configuration_ownership", "evidence"):
            step.pop(key)
    path.write_text(json.dumps(data))
    step = installer.load_record(plan.project_root).steps[0]
    assert step.configuration_intents == step.configuration_ownership == step.evidence == []


def test_receipt_staging_never_follows_predictable_tmp_symlink(tmp_path, configuration):
    plan, _ = configuration
    state = tmp_path / ".stackwinnow"
    state.mkdir()
    outside = tmp_path / "unrelated.txt"
    outside.write_bytes(b"preserve these bytes")
    (state / "receipts.tmp").symlink_to(outside)
    installer.execute_plan(plan)
    assert outside.read_bytes() == b"preserve these bytes"
    assert (state / "receipts.tmp").is_symlink()
    assert (state / "receipts.json").stat().st_mode & 0o777 == 0o600
    assert not list(state.glob(".receipts-*.tmp"))


@pytest.fixture
def published_with_cleanup_failure(tmp_path, configuration, monkeypatch):
    plan, _ = configuration
    target = tmp_path / "settings.json"
    target.write_text('{"enabled":"original"}')
    patch = plan_json_edits(
        plan.project_root,
        target.name,
        tool_id="promptfoo",
        edits=[JsonConfigEdit(key_path=("enabled",), value="managed", replace_existing=True)],
    )
    unlink = os.unlink

    def fail_cleanup(path, **kwargs):
        if isinstance(path, str) and path.startswith(".stackwinnow-"):
            raise PermissionError("simulated configuration cleanup failure")
        unlink(path, **kwargs)

    def publish(step):
        with monkeypatch.context() as changes:
            changes.setattr(os, "unlink", fail_cleanup)
            outcome = apply_json_edits(patch)
        assert outcome.result.status == "failed" and outcome.ownership == patch
        return installer.RunnerOutcome(
            status=outcome.result.status,
            message=outcome.result.message,
            configuration_ownership=[outcome.ownership],
        )

    installer.execute_plan(
        plan, step_runner=publish, configuration_intents={plan.steps[0].step_id: [patch]}
    )
    assert json.loads(target.read_text())["enabled"] == "managed"
    return plan, patch


@pytest.mark.parametrize("interrupted", [False, True])
def test_retry_preserves_ownership_in_intent_and_noop_outcome(
    published_with_cleanup_failure, interrupted
):
    plan, original = published_with_cleanup_failure
    step_id = plan.steps[0].step_id
    retry_patch = plan_json_edits(
        plan.project_root,
        original.relative_path,
        tool_id="promptfoo",
        edits=[JsonConfigEdit(key_path=("enabled",), value="managed")],
    )
    assert retry_patch.edits == ()

    def retry(step):
        saved = installer.load_record(plan.project_root).receipt_for(step_id)
        assert saved.status == "failed"
        assert saved.configuration_ownership == [original]
        assert saved.configuration_intents == [original, retry_patch]
        if interrupted:
            raise RuntimeError("simulated interruption after retry intent")
        outcome = apply_json_edits(retry_patch)
        assert outcome.result.status == "skipped" and outcome.ownership is None
        return installer.RunnerOutcome(status="skipped", message=outcome.result.message)

    if interrupted:
        with pytest.raises(RuntimeError, match="simulated interruption"):
            installer.execute_plan(
                plan, step_runner=retry, configuration_intents={step_id: [retry_patch]}
            )
    else:
        installer.execute_plan(
            plan, step_runner=retry, configuration_intents={step_id: [retry_patch]}
        )
    saved = installer.load_record(plan.project_root).receipt_for(step_id)
    assert saved.status == ("failed" if interrupted else "skipped")
    assert saved.configuration_ownership == [original]
    assert saved.configuration_ownership[0].edits[0].original.value == "original"


def test_retry_without_runner_retains_configuration_history(published_with_cleanup_failure):
    plan, patch = published_with_cleanup_failure
    record, results = installer.execute_plan(plan)
    assert results[0].status == "blocked"
    assert record.steps[0].configuration_ownership == [patch]
    assert record.steps[0].configuration_intents == [patch]
    assert installer.load_record(plan.project_root) == record


def test_retry_adds_new_ownership_without_losing_original(published_with_cleanup_failure):
    plan, original = published_with_cleanup_failure
    changed = plan_json_edits(
        plan.project_root,
        original.relative_path,
        tool_id="promptfoo",
        edits=[JsonConfigEdit(key_path=("enabled",), value="new value", replace_existing=True)],
    )

    def retry(step):
        outcome = apply_json_edits(changed)
        return installer.RunnerOutcome(
            status=outcome.result.status,
            message=outcome.result.message,
            configuration_ownership=[outcome.ownership],
        )

    record, results = installer.execute_plan(
        plan, step_runner=retry, configuration_intents={plan.steps[0].step_id: [changed]}
    )
    assert results[0].status == "succeeded"
    assert record.steps[0].configuration_ownership == [original, changed]
    assert record.steps[0].configuration_intents == [original, changed]


def test_copied_invalid_intent_is_revalidated_before_writes(tmp_path, configuration):
    plan, patch = configuration
    invalid = patch.model_copy(update={"relative_path": "../outside.json"})
    with pytest.raises(ValidationError):
        installer.execute_plan(plan, configuration_intents={plan.steps[0].step_id: [invalid]})
    assert list(tmp_path.iterdir()) == []


def test_intent_snapshot_is_detached_from_mutable_json(configuration):
    plan, _ = configuration
    patch = plan_json_edits(
        plan.project_root,
        "settings.json",
        tool_id="promptfoo",
        edits=[JsonConfigEdit(key_path=("options",), value={"items": []})],
    )

    def mutate_caller(step):
        patch.edits[0].written["items"].append("changed after intent")
        return installer.RunnerOutcome(status="blocked", message="No configuration applied.")

    record, _ = installer.execute_plan(
        plan, step_runner=mutate_caller, configuration_intents={plan.steps[0].step_id: [patch]}
    )
    saved = installer.load_record(plan.project_root)
    assert saved == record
    assert saved.steps[0].configuration_intents[0].edits[0].written == {"items": []}

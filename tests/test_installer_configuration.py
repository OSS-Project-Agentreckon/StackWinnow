"""Exercise durable configuration intent and ownership across executor failures."""

from __future__ import annotations

import hashlib
import json
import os

import pytest

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

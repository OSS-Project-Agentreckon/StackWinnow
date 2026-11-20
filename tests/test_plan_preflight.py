"""Tests for pre-flight plan validation and existing-installation detection.

No real tools are installed, no real environments are created, and no
subprocess calls are made. External PATH detection is patched; managed
environment directories are created as bare directories where needed.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from stackwinnow.catalog import EligibilityContext, Platform, load_catalog
from stackwinnow.contracts import InstallPlan, IntegrationAvailability, OperationStatus, PlanStep
from stackwinnow.installer import _receipts_path
from stackwinnow.plan import (
    PreflightCheck,
    PreflightError,
    PreflightReport,
    PreflightStatus,
    _find_external_executable,
    _has_managed_env,
    check_plan,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_PROMPTFOO_STEP = PlanStep(
    step_id="install-promptfoo",
    tool_id="promptfoo",
    description="Install promptfoo",
)

_HEADROOM_STEP = PlanStep(
    step_id="install-headroom",
    tool_id="headroom",
    description="Install Headroom",
)


def _plan(project_root: str, steps: list[PlanStep] | None = None) -> InstallPlan:
    steps = steps or [_PROMPTFOO_STEP]
    return InstallPlan(
        project_root=project_root,
        tool_ids=[s.tool_id for s in steps],
        steps=steps,
    )


def _write_receipt(tmp_path: Path, step: PlanStep, status: str = "succeeded") -> None:
    """Write a minimal receipt file recording one step outcome."""
    receipts_dir = tmp_path / ".stackwinnow"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 1,
        "project_root": str(tmp_path),
        "steps": [
            {
                "schema_version": 1,
                "step_id": step.step_id,
                "tool_id": step.tool_id,
                "status": status,
                "message": f"Step {step.step_id}.",
                "timestamp": "2026-11-19T00:00:00+00:00",
            }
        ],
    }
    (receipts_dir / "receipts.json").write_text(json.dumps(record), encoding="utf-8")


def _make_managed_python_env(tmp_path: Path, tool_id: str) -> Path:
    """Create the managed Python venv directory stub for tool_id."""
    env_dir = tmp_path / ".stackwinnow" / "envs" / tool_id / "python"
    env_dir.mkdir(parents=True, exist_ok=True)
    return env_dir


def _adapter_ready_catalog(*tool_ids: str) -> object:
    """Return a catalog with the named tools set to adapter_available, macos, claude-code."""
    catalog = load_catalog()
    tools = []
    for t in catalog.tools:
        if t.tool_id in tool_ids:
            tools.append(
                t.model_copy(
                    update={
                        "availability": IntegrationAvailability.ADAPTER_AVAILABLE,
                        "supported_platforms": [Platform.MACOS],
                        "supported_assistants": ["claude-code"],
                    },
                    deep=True,
                )
            )
        else:
            tools.append(t)
    return catalog.model_copy(update={"tools": tuple(tools)}, deep=True)


def _ready_context(*tool_ids: str) -> EligibilityContext:
    """Return a full eligibility context showing readiness for the named tools."""
    return EligibilityContext(
        platform=Platform.MACOS,
        assistant="claude-code",
        registered_adapters=list(tool_ids),
        prerequisite_checks={tid: OperationStatus.SUCCEEDED for tid in tool_ids},
    )


# ---------------------------------------------------------------------------
# PreflightReport properties
# ---------------------------------------------------------------------------


def test_report_is_ready_to_apply_when_all_ready(tmp_path: Path) -> None:
    report = PreflightReport(
        project_root=str(tmp_path),
        checks=[
            PreflightCheck(
                step_id="s1",
                tool_id="promptfoo",
                status=PreflightStatus.READY,
                message="ok",
            )
        ],
    )
    assert report.is_ready_to_apply


def test_report_is_ready_to_apply_when_skip_managed(tmp_path: Path) -> None:
    report = PreflightReport(
        project_root=str(tmp_path),
        checks=[
            PreflightCheck(
                step_id="s1",
                tool_id="promptfoo",
                status=PreflightStatus.SKIP_ALREADY_MANAGED,
                message="skip",
            )
        ],
    )
    assert report.is_ready_to_apply


def test_report_is_not_ready_when_blocked(tmp_path: Path) -> None:
    report = PreflightReport(
        project_root=str(tmp_path),
        checks=[
            PreflightCheck(
                step_id="s1",
                tool_id="promptfoo",
                status=PreflightStatus.BLOCKED,
                message="blocked",
            )
        ],
    )
    assert not report.is_ready_to_apply


def test_report_is_not_ready_when_stale_receipt(tmp_path: Path) -> None:
    report = PreflightReport(
        project_root=str(tmp_path),
        checks=[
            PreflightCheck(
                step_id="s1",
                tool_id="promptfoo",
                status=PreflightStatus.STALE_RECEIPT,
                message="stale",
            )
        ],
    )
    assert not report.is_ready_to_apply


def test_external_install_detected_does_not_block_apply(tmp_path: Path) -> None:
    report = PreflightReport(
        project_root=str(tmp_path),
        checks=[
            PreflightCheck(
                step_id="s1",
                tool_id="promptfoo",
                status=PreflightStatus.EXTERNAL_INSTALL_DETECTED,
                message="external",
                external_path="/usr/local/bin/promptfoo",
            )
        ],
    )
    assert report.is_ready_to_apply


def test_blocked_checks_returns_only_blocked(tmp_path: Path) -> None:
    report = PreflightReport(
        project_root=str(tmp_path),
        checks=[
            PreflightCheck(
                step_id="s1",
                tool_id="promptfoo",
                status=PreflightStatus.READY,
                message="ok",
            ),
            PreflightCheck(
                step_id="s2",
                tool_id="headroom",
                status=PreflightStatus.BLOCKED,
                message="blocked",
            ),
        ],
    )
    blocked = report.blocked_checks
    assert len(blocked) == 1
    assert blocked[0].tool_id == "headroom"


# ---------------------------------------------------------------------------
# _has_managed_env
# ---------------------------------------------------------------------------


def test_has_managed_env_false_when_no_dirs(tmp_path: Path) -> None:
    assert not _has_managed_env(str(tmp_path), "promptfoo")


def test_has_managed_env_true_when_python_venv_exists(tmp_path: Path) -> None:
    _make_managed_python_env(tmp_path, "headroom")
    assert _has_managed_env(str(tmp_path), "headroom")


def test_has_managed_env_false_for_different_tool(tmp_path: Path) -> None:
    _make_managed_python_env(tmp_path, "headroom")
    assert not _has_managed_env(str(tmp_path), "promptfoo")


def test_has_managed_env_true_when_node_env_exists(tmp_path: Path) -> None:
    node_dir = tmp_path / ".stackwinnow" / "envs" / "promptfoo" / "node"
    node_dir.mkdir(parents=True)
    assert _has_managed_env(str(tmp_path), "promptfoo")


def test_has_managed_env_false_when_regular_file_at_python_path(tmp_path: Path) -> None:
    """A regular file at the env path must not be treated as a managed install."""
    env_path = tmp_path / ".stackwinnow" / "envs" / "promptfoo" / "python"
    env_path.parent.mkdir(parents=True)
    env_path.write_text("not a dir", encoding="utf-8")
    assert not _has_managed_env(str(tmp_path), "promptfoo")


def test_has_managed_env_false_when_symlink_at_python_path(tmp_path: Path) -> None:
    """A symlink pointing at a directory must not be treated as a managed install."""
    real_dir = tmp_path / "real-env"
    real_dir.mkdir()
    env_path = tmp_path / ".stackwinnow" / "envs" / "promptfoo" / "python"
    env_path.parent.mkdir(parents=True)
    env_path.symlink_to(real_dir)
    assert not _has_managed_env(str(tmp_path), "promptfoo")


# ---------------------------------------------------------------------------
# _find_external_executable
# ---------------------------------------------------------------------------


def test_find_external_returns_none_when_not_on_path(tmp_path: Path) -> None:
    with patch("shutil.which", return_value=None):
        assert _find_external_executable(str(tmp_path), "promptfoo") is None


def test_find_external_returns_path_when_on_system_path(tmp_path: Path) -> None:
    external = "/usr/local/bin/promptfoo"
    with patch("shutil.which", return_value=external):
        result = _find_external_executable(str(tmp_path), "promptfoo")
    assert result == external


def test_find_external_returns_none_when_inside_managed_root(tmp_path: Path) -> None:
    managed_bin = str(
        tmp_path / ".stackwinnow" / "envs" / "promptfoo" / "node" / ".bin" / "promptfoo"
    )
    with patch("shutil.which", return_value=managed_bin):
        assert _find_external_executable(str(tmp_path), "promptfoo") is None


def test_find_external_returns_path_for_sibling_managed_root(tmp_path: Path) -> None:
    """A tool in .stackwinnow-backup (string-prefix sibling) must not be hidden."""
    sibling_bin = str(
        tmp_path / ".stackwinnow-backup" / "envs" / "promptfoo" / "node" / ".bin" / "promptfoo"
    )
    with patch("shutil.which", return_value=sibling_bin):
        result = _find_external_executable(str(tmp_path), "promptfoo")
    assert result == sibling_bin


# ---------------------------------------------------------------------------
# check_plan — READY path
# ---------------------------------------------------------------------------


def test_check_plan_ready_for_uninstalled_eligible_tool(tmp_path: Path) -> None:
    catalog = _adapter_ready_catalog("promptfoo")
    context = _ready_context("promptfoo")
    with patch("shutil.which", return_value=None):
        report = check_plan(_plan(str(tmp_path)), catalog=catalog, context=context)
    assert len(report.checks) == 1
    assert report.checks[0].status == PreflightStatus.READY
    assert report.is_ready_to_apply


def test_check_plan_reports_project_root(tmp_path: Path) -> None:
    catalog = _adapter_ready_catalog("promptfoo")
    context = _ready_context("promptfoo")
    with patch("shutil.which", return_value=None):
        report = check_plan(_plan(str(tmp_path)), catalog=catalog, context=context)
    assert report.project_root == str(tmp_path)


def test_check_plan_ready_carries_step_and_tool_ids(tmp_path: Path) -> None:
    catalog = _adapter_ready_catalog("promptfoo")
    context = _ready_context("promptfoo")
    with patch("shutil.which", return_value=None):
        report = check_plan(_plan(str(tmp_path)), catalog=catalog, context=context)
    check = report.checks[0]
    assert check.step_id == "install-promptfoo"
    assert check.tool_id == "promptfoo"


def test_check_plan_produces_one_check_per_step(tmp_path: Path) -> None:
    catalog = _adapter_ready_catalog("promptfoo", "headroom")
    context = _ready_context("promptfoo", "headroom")
    plan = _plan(str(tmp_path), steps=[_PROMPTFOO_STEP, _HEADROOM_STEP])
    with patch("shutil.which", return_value=None):
        report = check_plan(plan, catalog=catalog, context=context)
    assert len(report.checks) == 2


def test_check_plan_empty_plan_returns_empty_report(tmp_path: Path) -> None:
    plan = InstallPlan(project_root=str(tmp_path), tool_ids=[], steps=[])
    report = check_plan(plan)
    assert report.checks == []
    assert report.is_ready_to_apply


# ---------------------------------------------------------------------------
# check_plan — BLOCKED: tool not in catalog
# ---------------------------------------------------------------------------


def test_check_plan_blocked_when_tool_not_in_catalog(tmp_path: Path) -> None:
    plan = InstallPlan(
        project_root=str(tmp_path),
        tool_ids=["no-such-tool"],
        steps=[
            PlanStep(
                step_id="install-no-such-tool",
                tool_id="no-such-tool",
                description="Install something not in the catalog",
            )
        ],
    )
    with patch("shutil.which", return_value=None):
        report = check_plan(plan)
    assert report.checks[0].status == PreflightStatus.BLOCKED
    assert not report.is_ready_to_apply


def test_check_plan_blocked_message_names_missing_tool(tmp_path: Path) -> None:
    plan = InstallPlan(
        project_root=str(tmp_path),
        tool_ids=["no-such-tool"],
        steps=[
            PlanStep(
                step_id="install-no-such-tool",
                tool_id="no-such-tool",
                description="Install something not in the catalog",
            )
        ],
    )
    with patch("shutil.which", return_value=None):
        report = check_plan(plan)
    assert "no-such-tool" in report.checks[0].message


# ---------------------------------------------------------------------------
# check_plan — BLOCKED: unresolved license
# ---------------------------------------------------------------------------


def test_check_plan_blocked_when_license_unresolved(tmp_path: Path) -> None:
    catalog = load_catalog()
    # Reuse a real entry but patch its license_review field via model_copy
    patched = catalog.get("promptfoo").model_copy(
        update={"license_review": "unresolved"}, deep=True
    )
    patched_catalog = catalog.model_copy(
        update={"tools": tuple(patched if t.tool_id == "promptfoo" else t for t in catalog.tools)},
        deep=True,
    )
    with patch("shutil.which", return_value=None):
        report = check_plan(_plan(str(tmp_path)), catalog=patched_catalog)
    assert report.checks[0].status == PreflightStatus.BLOCKED
    assert any("license" in r.lower() for r in report.checks[0].reasons)


# ---------------------------------------------------------------------------
# check_plan — BLOCKED: missing eligibility evidence (P1 regressions)
# ---------------------------------------------------------------------------


def test_check_plan_blocked_when_prerequisites_failed(tmp_path: Path) -> None:
    """Failed prerequisite check must block even when all other evidence is present."""
    catalog = _adapter_ready_catalog("promptfoo")
    context = EligibilityContext(
        platform=Platform.MACOS,
        assistant="claude-code",
        registered_adapters=["promptfoo"],
        prerequisite_checks={"promptfoo": OperationStatus.FAILED},
    )
    with patch("shutil.which", return_value=None):
        report = check_plan(_plan(str(tmp_path)), catalog=catalog, context=context)
    assert report.checks[0].status == PreflightStatus.BLOCKED
    assert any("prerequisite" in r.lower() for r in report.checks[0].reasons)


def test_check_plan_blocked_when_adapter_unavailable(tmp_path: Path) -> None:
    """catalog_only availability must block even with a full eligibility context."""
    # promptfoo is catalog_only in the unpatched catalog
    context = _ready_context("promptfoo")
    with patch("shutil.which", return_value=None):
        report = check_plan(_plan(str(tmp_path)), context=context)
    assert report.checks[0].status == PreflightStatus.BLOCKED
    assert any("adapter" in r.lower() for r in report.checks[0].reasons)


def test_check_plan_blocked_when_platform_unknown(tmp_path: Path) -> None:
    """No platform in the context must block — absent evidence is not readiness."""
    catalog = _adapter_ready_catalog("promptfoo")
    context = EligibilityContext(
        assistant="claude-code",
        registered_adapters=["promptfoo"],
        prerequisite_checks={"promptfoo": OperationStatus.SUCCEEDED},
    )
    with patch("shutil.which", return_value=None):
        report = check_plan(_plan(str(tmp_path)), catalog=catalog, context=context)
    assert report.checks[0].status == PreflightStatus.BLOCKED


# ---------------------------------------------------------------------------
# check_plan — BLOCKED: platform mismatch
# ---------------------------------------------------------------------------


def test_check_plan_blocked_when_platform_unsupported(tmp_path: Path) -> None:
    catalog = load_catalog()
    # Pin promptfoo to only macos so we can test a linux mismatch
    patched = catalog.get("promptfoo").model_copy(
        update={"supported_platforms": [Platform.MACOS]}, deep=True
    )
    patched_catalog = catalog.model_copy(
        update={"tools": tuple(patched if t.tool_id == "promptfoo" else t for t in catalog.tools)},
        deep=True,
    )
    context = EligibilityContext(platform=Platform.LINUX)
    with patch("shutil.which", return_value=None):
        report = check_plan(_plan(str(tmp_path)), catalog=patched_catalog, context=context)
    assert report.checks[0].status == PreflightStatus.BLOCKED
    assert not report.is_ready_to_apply


def test_check_plan_ready_when_platform_matches(tmp_path: Path) -> None:
    catalog = _adapter_ready_catalog("promptfoo")  # supported_platforms=[MACOS]
    context = _ready_context("promptfoo")  # platform=MACOS
    with patch("shutil.which", return_value=None):
        report = check_plan(_plan(str(tmp_path)), catalog=catalog, context=context)
    assert report.checks[0].status == PreflightStatus.READY


def test_check_plan_blocked_when_platform_unverified(tmp_path: Path) -> None:
    """An empty supported_platforms list means 'unverified' — conservative gate blocks it."""
    catalog = load_catalog()
    # Patch promptfoo to be adapter_available but with no documented platforms
    patched = catalog.get("promptfoo").model_copy(
        update={
            "availability": IntegrationAvailability.ADAPTER_AVAILABLE,
            "supported_platforms": [],
            "supported_assistants": ["claude-code"],
        },
        deep=True,
    )
    patched_catalog = catalog.model_copy(
        update={"tools": tuple(patched if t.tool_id == "promptfoo" else t for t in catalog.tools)},
        deep=True,
    )
    context = EligibilityContext(
        platform=Platform.LINUX,
        assistant="claude-code",
        registered_adapters=["promptfoo"],
        prerequisite_checks={"promptfoo": OperationStatus.SUCCEEDED},
    )
    with patch("shutil.which", return_value=None):
        report = check_plan(_plan(str(tmp_path)), catalog=patched_catalog, context=context)
    assert report.checks[0].status == PreflightStatus.BLOCKED


# ---------------------------------------------------------------------------
# check_plan — SKIP_ALREADY_MANAGED
# ---------------------------------------------------------------------------


def test_check_plan_skip_when_receipt_succeeded_and_env_exists(tmp_path: Path) -> None:
    _write_receipt(tmp_path, _PROMPTFOO_STEP, status="succeeded")
    _make_managed_python_env(tmp_path, "promptfoo")
    with patch("shutil.which", return_value=None):
        report = check_plan(_plan(str(tmp_path)))
    assert report.checks[0].status == PreflightStatus.SKIP_ALREADY_MANAGED
    assert report.is_ready_to_apply


def test_check_plan_skip_message_names_tool(tmp_path: Path) -> None:
    _write_receipt(tmp_path, _PROMPTFOO_STEP, status="succeeded")
    _make_managed_python_env(tmp_path, "promptfoo")
    with patch("shutil.which", return_value=None):
        report = check_plan(_plan(str(tmp_path)))
    assert "promptfoo" in report.checks[0].message


def test_check_plan_not_skipped_when_receipt_failed(tmp_path: Path) -> None:
    """A FAILED receipt does not cause skip — the step should be retried."""
    _write_receipt(tmp_path, _PROMPTFOO_STEP, status="failed")
    catalog = _adapter_ready_catalog("promptfoo")
    context = _ready_context("promptfoo")
    with patch("shutil.which", return_value=None):
        report = check_plan(_plan(str(tmp_path)), catalog=catalog, context=context)
    assert report.checks[0].status == PreflightStatus.READY


def test_check_plan_not_skipped_for_different_tool_same_step_id(tmp_path: Path) -> None:
    """is_succeeded checks both step_id AND tool_id — different tool must not skip."""
    _write_receipt(tmp_path, _PROMPTFOO_STEP, status="succeeded")
    _make_managed_python_env(tmp_path, "promptfoo")
    # Plan uses headroom with the SAME step_id as the promptfoo receipt
    headroom_step = PlanStep(
        step_id="install-promptfoo",  # same step_id
        tool_id="headroom",  # different tool_id
        description="Install Headroom with the same step id",
    )
    plan = InstallPlan(project_root=str(tmp_path), tool_ids=["headroom"], steps=[headroom_step])
    catalog = _adapter_ready_catalog("headroom")
    context = _ready_context("headroom")
    with patch("shutil.which", return_value=None):
        report = check_plan(plan, catalog=catalog, context=context)
    # The receipt is for promptfoo, not headroom — headroom must not be skipped
    assert report.checks[0].status == PreflightStatus.READY


# ---------------------------------------------------------------------------
# check_plan — STALE_RECEIPT
# ---------------------------------------------------------------------------


def test_check_plan_stale_when_receipt_succeeded_but_env_gone(tmp_path: Path) -> None:
    _write_receipt(tmp_path, _PROMPTFOO_STEP, status="succeeded")
    # Intentionally do NOT create the managed env
    with patch("shutil.which", return_value=None):
        report = check_plan(_plan(str(tmp_path)))
    assert report.checks[0].status == PreflightStatus.STALE_RECEIPT
    assert not report.is_ready_to_apply


def test_check_plan_stale_message_names_tool(tmp_path: Path) -> None:
    _write_receipt(tmp_path, _PROMPTFOO_STEP, status="succeeded")
    with patch("shutil.which", return_value=None):
        report = check_plan(_plan(str(tmp_path)))
    assert "promptfoo" in report.checks[0].message


# ---------------------------------------------------------------------------
# check_plan — SKIP / STALE across run IDs (P2 line 161 regressions)
# ---------------------------------------------------------------------------


def test_check_plan_skip_with_fresh_step_id_when_env_exists(tmp_path: Path) -> None:
    """A new step_id for the same tool must still produce SKIP when the env is present."""
    old_step = PlanStep(
        step_id="install-promptfoo-run1", tool_id="promptfoo", description="Install promptfoo"
    )
    _write_receipt(tmp_path, old_step, status="succeeded")
    _make_managed_python_env(tmp_path, "promptfoo")
    new_step = PlanStep(
        step_id="install-promptfoo-run2", tool_id="promptfoo", description="Install promptfoo"
    )
    with patch("shutil.which", return_value=None):
        report = check_plan(_plan(str(tmp_path), steps=[new_step]))
    assert report.checks[0].status == PreflightStatus.SKIP_ALREADY_MANAGED


def test_check_plan_stale_with_fresh_step_id_when_env_gone(tmp_path: Path) -> None:
    """A new step_id for the same tool must surface STALE when the env has been removed."""
    old_step = PlanStep(
        step_id="install-promptfoo-run1", tool_id="promptfoo", description="Install promptfoo"
    )
    _write_receipt(tmp_path, old_step, status="succeeded")
    # Intentionally do NOT create the managed env
    new_step = PlanStep(
        step_id="install-promptfoo-run2", tool_id="promptfoo", description="Install promptfoo"
    )
    with patch("shutil.which", return_value=None):
        report = check_plan(_plan(str(tmp_path), steps=[new_step]))
    assert report.checks[0].status == PreflightStatus.STALE_RECEIPT


# ---------------------------------------------------------------------------
# check_plan — EXTERNAL_INSTALL_DETECTED
# ---------------------------------------------------------------------------


def test_check_plan_external_install_detected(tmp_path: Path) -> None:
    external = "/usr/local/bin/promptfoo"
    with patch("shutil.which", return_value=external):
        report = check_plan(_plan(str(tmp_path)))
    check = report.checks[0]
    assert check.status == PreflightStatus.EXTERNAL_INSTALL_DETECTED
    assert check.external_path == external
    assert report.is_ready_to_apply  # external does NOT block apply


def test_check_plan_external_path_in_message(tmp_path: Path) -> None:
    external = "/usr/local/bin/promptfoo"
    with patch("shutil.which", return_value=external):
        report = check_plan(_plan(str(tmp_path)))
    assert external in report.checks[0].message


def test_check_plan_managed_install_takes_priority_over_external(tmp_path: Path) -> None:
    """If managed install exists with a succeeded receipt, skip takes priority over external."""
    _write_receipt(tmp_path, _PROMPTFOO_STEP, status="succeeded")
    _make_managed_python_env(tmp_path, "promptfoo")
    external = "/usr/local/bin/promptfoo"
    with patch("shutil.which", return_value=external):
        report = check_plan(_plan(str(tmp_path)))
    assert report.checks[0].status == PreflightStatus.SKIP_ALREADY_MANAGED


# ---------------------------------------------------------------------------
# check_plan — PreflightError on corrupt receipts
# ---------------------------------------------------------------------------


def test_check_plan_raises_preflight_error_on_corrupt_receipts(tmp_path: Path) -> None:
    receipts_dir = tmp_path / ".stackwinnow"
    receipts_dir.mkdir()
    (receipts_dir / "receipts.json").write_text("not valid json", encoding="utf-8")
    with pytest.raises(PreflightError, match="corrupt"):
        check_plan(_plan(str(tmp_path)))


def test_check_plan_raises_preflight_error_on_project_root_mismatch(tmp_path: Path) -> None:
    project_a = tmp_path / "a"
    project_b = tmp_path / "b"
    project_a.mkdir()
    project_b.mkdir()

    # Write a valid receipt for project_a
    _write_receipt(project_a, _PROMPTFOO_STEP, status="succeeded")
    # Copy it into project_b's state directory
    (project_b / ".stackwinnow").mkdir()
    receipts_a = _receipts_path(str(project_a))
    (project_b / ".stackwinnow" / "receipts.json").write_bytes(receipts_a.read_bytes())

    with pytest.raises(PreflightError, match="project root"):
        check_plan(_plan(str(project_b)))


# ---------------------------------------------------------------------------
# check_plan — multi-step plans
# ---------------------------------------------------------------------------


def test_check_plan_checks_each_step_independently(tmp_path: Path) -> None:
    _write_receipt(tmp_path, _PROMPTFOO_STEP, status="succeeded")
    _make_managed_python_env(tmp_path, "promptfoo")
    catalog = _adapter_ready_catalog("promptfoo", "headroom")
    context = _ready_context("promptfoo", "headroom")
    plan = _plan(str(tmp_path), steps=[_PROMPTFOO_STEP, _HEADROOM_STEP])
    with patch("shutil.which", return_value=None):
        report = check_plan(plan, catalog=catalog, context=context)
    assert len(report.checks) == 2
    assert report.checks[0].status == PreflightStatus.SKIP_ALREADY_MANAGED
    assert report.checks[1].status == PreflightStatus.READY


def test_check_plan_blocked_step_does_not_affect_others(tmp_path: Path) -> None:
    """Other steps are still individually checked even if one step is blocked."""
    catalog = _adapter_ready_catalog("promptfoo")
    context = _ready_context("promptfoo")
    plan = InstallPlan(
        project_root=str(tmp_path),
        tool_ids=["no-such-tool", "promptfoo"],
        steps=[
            PlanStep(
                step_id="install-no-such-tool",
                tool_id="no-such-tool",
                description="Install absent tool",
            ),
            _PROMPTFOO_STEP,
        ],
    )
    with patch("shutil.which", return_value=None):
        report = check_plan(plan, catalog=catalog, context=context)
    assert report.checks[0].status == PreflightStatus.BLOCKED
    assert report.checks[1].status == PreflightStatus.READY
    assert not report.is_ready_to_apply  # one blocked step stops the whole plan

"""Failing tests for B06 — Headroom CLI and verification integration.

Written before implementation; all must fail initially.
Once cli.py wires up the headroom subcommand, all tests must pass.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from stackwinnow import cli
from stackwinnow.adapters.headroom import (
    CompressionEvidence,
    HeadroomError,
    HeadroomPlan,
    HeadroomResult,
)
from stackwinnow.contracts import OperationResult, OperationStatus
from stackwinnow.installer import ExecutionRecord, PlanStep

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plan(project_root: str) -> HeadroomPlan:
    """Build a minimal HeadroomPlan for use in tests."""
    from stackwinnow.contracts import InstallPlan

    installation = InstallPlan(
        project_root=project_root,
        tool_ids=["headroom"],
        steps=[
            PlanStep(step_id="headroom-abc123-install", tool_id="headroom", description="Install"),
            PlanStep(step_id="headroom-abc123-compress", tool_id="headroom", description="Compress"),
        ],
    )
    return HeadroomPlan(
        run_id="a" * 32,
        project_root=project_root,
        installation=installation,
    )


def _make_result(plan: HeadroomPlan, *, status=OperationStatus.SUCCEEDED) -> HeadroomResult:
    return HeadroomResult(
        plan=plan,
        status=status,
        message="headroom is installed and library-mode compression passed.",
        dry_run=False,
        results=[
            OperationResult(
                step_id="headroom-abc123-install",
                tool_id="headroom",
                status=OperationStatus.SUCCEEDED,
                message="headroom-ai 0.44.0 installed.",
            ),
            OperationResult(
                step_id="headroom-abc123-compress",
                tool_id="headroom",
                status=status,
                message="Fixture compression succeeded.",
            ),
        ],
        record=ExecutionRecord(project_root=plan.project_root),
        compression=CompressionEvidence(messages_in=2, messages_out=2, tokens_saved=10)
        if status == OperationStatus.SUCCEEDED
        else None,
    )


# ---------------------------------------------------------------------------
# 1. Plan subcommand — human-readable output
# ---------------------------------------------------------------------------


def test_headroom_plan_prints_human_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """stackwinnow headroom plan <dir> must print a human-readable plan summary."""
    plan = _make_plan(str(tmp_path))

    monkeypatch.setattr(
        "stackwinnow.adapters.headroom.plan_headroom",
        lambda *a, **kw: plan,
    )

    code = cli.main(["headroom", "plan", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 0
    assert "headroom" in out.lower()


# ---------------------------------------------------------------------------
# 2. Plan subcommand — JSON output
# ---------------------------------------------------------------------------


def test_headroom_plan_json_emits_valid_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """stackwinnow headroom plan --json must emit a parseable HeadroomPlan payload."""
    plan = _make_plan(str(tmp_path))

    monkeypatch.setattr(
        "stackwinnow.adapters.headroom.plan_headroom",
        lambda *a, **kw: plan,
    )

    code = cli.main(["headroom", "plan", str(tmp_path), "--json"])

    out = capsys.readouterr().out
    assert code == 0
    payload = json.loads(out)
    assert payload["tool_id"] == "headroom"
    assert payload["version"] == "0.44.0"


# ---------------------------------------------------------------------------
# 3. Apply subcommand — dry run
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def test_headroom_apply_dry_run_does_not_call_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """stackwinnow headroom apply PLAN.json --dry-run must not write files."""
    plan = _make_plan(str(tmp_path))
    plan_file = tmp_path / "headroom-plan.json"
    plan_file.write_text(plan.model_dump_json())

    dry_result = HeadroomResult(
        plan=plan,
        status=OperationStatus.SKIPPED,
        message="Dry run; no commands or files were created.",
        dry_run=True,
        record=ExecutionRecord(project_root=str(tmp_path)),
    )

    monkeypatch.setattr(
        "stackwinnow.adapters.headroom.apply_headroom",
        lambda p, dry_run=False, **kw: dry_result,
    )
    monkeypatch.setattr(
        "stackwinnow.adapters.headroom.HeadroomPlan.model_validate_json",
        lambda s: plan,
    )

    code = cli.main(["headroom", "apply", str(plan_file), "--dry-run"])

    out = capsys.readouterr().out
    assert code == 0
    assert "dry" in out.lower() or "skipped" in out.lower()


# ---------------------------------------------------------------------------
# 4. Apply subcommand — successful apply
# ---------------------------------------------------------------------------


def test_headroom_apply_success_exits_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """stackwinnow headroom apply must exit 0 on succeeded result."""
    plan = _make_plan(str(tmp_path))
    plan_file = tmp_path / "headroom-plan.json"
    plan_file.write_text(plan.model_dump_json())
    result = _make_result(plan)

    monkeypatch.setattr(
        "stackwinnow.adapters.headroom.apply_headroom",
        lambda p, dry_run=False, **kw: result,
    )
    monkeypatch.setattr(
        "stackwinnow.adapters.headroom.HeadroomPlan.model_validate_json",
        lambda s: plan,
    )

    code = cli.main(["headroom", "apply", str(plan_file)])

    assert code == 0
    out = capsys.readouterr().out
    assert out  # something was printed


# ---------------------------------------------------------------------------
# 5. Apply subcommand — JSON output
# ---------------------------------------------------------------------------


def test_headroom_apply_json_emits_valid_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """stackwinnow headroom apply --json must emit parseable HeadroomResult JSON."""
    plan = _make_plan(str(tmp_path))
    plan_file = tmp_path / "headroom-plan.json"
    plan_file.write_text(plan.model_dump_json())
    result = _make_result(plan)

    monkeypatch.setattr(
        "stackwinnow.adapters.headroom.apply_headroom",
        lambda p, dry_run=False, **kw: result,
    )
    monkeypatch.setattr(
        "stackwinnow.adapters.headroom.HeadroomPlan.model_validate_json",
        lambda s: plan,
    )

    code = cli.main(["headroom", "apply", str(plan_file), "--json"])

    out = capsys.readouterr().out
    assert code == 0
    payload = json.loads(out)
    assert payload["plan"]["tool_id"] == "headroom"


# ---------------------------------------------------------------------------
# 6. Plan error exits with code 2
# ---------------------------------------------------------------------------


def test_headroom_plan_error_exits_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """HeadroomError during plan must produce exit code 2 and an error message."""

    def _fail(*a, **kw):
        raise HeadroomError("catalog unavailable")

    monkeypatch.setattr("stackwinnow.adapters.headroom.plan_headroom", _fail)

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["headroom", "plan", str(tmp_path)])

    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# 7. Apply blocked result exits non-zero
# ---------------------------------------------------------------------------


def test_headroom_apply_blocked_exits_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """stackwinnow headroom apply must exit non-zero when result is blocked."""
    plan = _make_plan(str(tmp_path))
    plan_file = tmp_path / "headroom-plan.json"
    plan_file.write_text(plan.model_dump_json())

    blocked_result = HeadroomResult(
        plan=plan,
        status=OperationStatus.BLOCKED,
        message="Platform not supported.",
        dry_run=False,
    )

    monkeypatch.setattr(
        "stackwinnow.adapters.headroom.apply_headroom",
        lambda p, dry_run=False, **kw: blocked_result,
    )
    monkeypatch.setattr(
        "stackwinnow.adapters.headroom.HeadroomPlan.model_validate_json",
        lambda s: plan,
    )

    code = cli.main(["headroom", "apply", str(plan_file)])

    assert code != 0

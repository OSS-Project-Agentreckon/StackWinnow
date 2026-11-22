"""Read-only reconciliation of an owned ConfigPatch against the current file.

No assistant or tool is executed; projects are copied fixtures.
"""

import json
import os

import pytest
from conftest import FixtureProject

from stackwinnow.configure import (
    apply_json_edits,
    plan_json_edits,
    reconcile_config_patch,
)
from stackwinnow.contracts import (
    ConfigPatch,
    ConfigReconcileReport,
    ConflictKind,
    FileState,
    JsonConfigEdit,
    KeyConflict,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="reconcile reads via POSIX file APIs")


def _apply_server(project: FixtureProject) -> ConfigPatch:
    edit = JsonConfigEdit(
        key_path=("mcpServers", "fixture-tool"),
        value={"command": "fixture-only-do-not-execute"},
    )
    patch = plan_json_edits(
        project.root, project.settings.name, tool_id="fixture-tool", edits=[edit]
    )
    assert apply_json_edits(patch).result.status == "succeeded"
    return patch


# --- Task 1: contracts -------------------------------------------------------


def test_report_safe_to_revert_only_when_readable_and_all_clean() -> None:
    clean = ConfigReconcileReport(
        project_root="/tmp/x",
        relative_path="a.json",
        tool_id="fixture-tool",
        file_state=FileState.READABLE,
        keys=(KeyConflict(key_path=("mcpServers", "fixture-tool"), kind=ConflictKind.CLEAN),),
    )
    assert clean.safe_to_revert is True
    assert clean.requires_attention == ()


def test_report_not_safe_when_a_key_conflicts() -> None:
    report = ConfigReconcileReport(
        project_root="/tmp/x",
        relative_path="a.json",
        tool_id="fixture-tool",
        file_state=FileState.READABLE,
        keys=(
            KeyConflict(key_path=("mcpServers", "fixture-tool"), kind=ConflictKind.USER_MODIFIED),
        ),
    )
    assert report.safe_to_revert is False
    assert len(report.requires_attention) == 1


def test_report_not_safe_when_file_unreadable_even_with_no_keys() -> None:
    report = ConfigReconcileReport(
        project_root="/tmp/x",
        relative_path="a.json",
        tool_id="fixture-tool",
        file_state=FileState.UNREADABLE,
    )
    assert report.safe_to_revert is False


def test_report_round_trips_through_json() -> None:
    report = ConfigReconcileReport(
        project_root="/tmp/x",
        relative_path="a.json",
        tool_id="fixture-tool",
        file_state=FileState.STALE,
    )
    assert ConfigReconcileReport.model_validate_json(report.model_dump_json()) == report

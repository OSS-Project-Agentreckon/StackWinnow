"""Check the data boundary shared by discovery, setup, and verification."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from stackwinnow.contracts import (
    InstallPlan,
    IntegrationAvailability,
    OperationResult,
    OperationStatus,
    PlanStep,
    ProjectProfile,
    ToolSpec,
)

TOOL = {
    "tool_id": "graphify",
    "name": "Graphify",
    "description": "Build a project knowledge graph.",
    "repository": "https://github.com/Graphify-Labs/graphify",
}
STEP = {
    "step_id": "check-graphify",
    "tool_id": "graphify",
    "description": "Check adapter availability",
}


def test_unknown_metadata_is_not_invented() -> None:
    profile = ProjectProfile(project_root="./sample project")
    tool = ToolSpec.model_validate(TOOL)

    assert profile.assistant is None
    assert profile.operating_system is None
    assert profile.facts == {}
    assert profile.evidence == []
    assert profile.goals == []
    assert tool.license is None
    assert tool.availability is IntegrationAvailability.CATALOG_ONLY


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (ProjectProfile, {"project_root": "./sample", "langauges": ["python"]}),
        (ToolSpec, {**TOOL, "licence": "MIT"}),
        (InstallPlan, {"project_root": "./sample", "tool_ids": [], "command": "echo ok"}),
    ],
)
def test_unrecognized_fields_are_rejected(model: type[BaseModel], data: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        model.model_validate(data)


@pytest.mark.parametrize("tool_id", ["../graphify", "graphify;echo", "Graphify", ""])
def test_tool_ids_cannot_be_paths_commands_or_malformed_identifiers(tool_id: str) -> None:
    with pytest.raises(ValidationError):
        ToolSpec.model_validate({**TOOL, "tool_id": tool_id})


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (ProjectProfile, {"project_root": "   "}),
        (OperationResult, {"status": "failed", "message": "\t"}),
        (PlanStep, {**STEP, "description": ""}),
    ],
)
def test_empty_required_text_is_rejected(model: type[BaseModel], data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(data)


@pytest.mark.parametrize("status_fields", [{}, {"status": "verified"}, {"status": "success"}])
def test_results_require_an_explicit_supported_status(status_fields: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        OperationResult.model_validate({"message": "Adapter has not run.", **status_fields})


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (ProjectProfile, {"project_root": "./sample"}),
        (ToolSpec, TOOL),
        (InstallPlan, {"project_root": "./sample", "tool_ids": []}),
        (OperationResult, {"status": "blocked", "message": "Adapter unavailable."}),
    ],
)
def test_unknown_schema_versions_are_rejected(
    model: type[BaseModel], data: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({**data, "schema_version": 2})


@pytest.mark.parametrize(
    ("tool_ids", "steps", "diagnostic"),
    [
        (["graphify", "graphify"], [], "tool_ids must be unique"),
        (["graphify"], [STEP, STEP], "step IDs must be unique"),
        (["headroom"], [STEP], "references an unselected tool"),
    ],
)
def test_plan_selection_and_step_references_are_consistent(
    tool_ids: list[str], steps: list[dict[str, str]], diagnostic: str
) -> None:
    with pytest.raises(ValidationError, match=diagnostic):
        InstallPlan(project_root="./sample", tool_ids=tool_ids, steps=steps)


def test_plan_and_result_json_round_trips_preserve_intent_and_evidence() -> None:
    plan = InstallPlan(
        project_root="./a project with spaces",
        assistant="example-assistant",
        tool_ids=["graphify"],
        steps=[
            STEP,
            {
                "step_id": "index-graphify",
                "tool_id": "graphify",
                "description": "Index only after prerequisite checks pass",
            },
        ],
    )
    result = OperationResult(
        status="blocked",
        tool_id="graphify",
        step_id="check-graphify",
        message="No adapter is implemented.",
        errors=["Integration unavailable"],
        evidence=[{"source": "catalog/graphify.yaml", "detail": "Catalog entry only"}],
    )

    restored_plan = InstallPlan.model_validate_json(plan.model_dump_json())
    restored_result = OperationResult.model_validate_json(result.model_dump_json())

    assert restored_plan == plan
    assert [step.step_id for step in restored_plan.steps] == ["check-graphify", "index-graphify"]
    assert restored_result == result
    assert restored_result.status is OperationStatus.BLOCKED
    assert restored_result.evidence[0].source == "catalog/graphify.yaml"


def test_empty_selection_is_a_valid_no_op_plan() -> None:
    plan = InstallPlan(project_root="./sample", tool_ids=[])

    assert plan.tool_ids == []
    assert plan.steps == []
    assert plan.assistant is None


def test_adapter_availability_does_not_mean_verified() -> None:
    tool = ToolSpec.model_validate({**TOOL, "availability": "adapter_available"})

    assert tool.availability is IntegrationAvailability.ADAPTER_AVAILABLE
    with pytest.raises(ValidationError):
        ToolSpec.model_validate({**TOOL, "availability": "verified"})


def test_import_and_construction_leave_project_and_settings_untouched(tmp_path: Path) -> None:
    settings = tmp_path / "assistant-settings.json"
    original_settings = b'{"existing_tool": "keep this"}\n'
    settings.write_bytes(original_settings)
    missing_project = tmp_path / "project that does not exist"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from stackwinnow.contracts import ProjectProfile, InstallPlan; "
            "import sys; "
            "profile = ProjectProfile(project_root=sys.argv[1]); "
            "InstallPlan(project_root=profile.project_root, tool_ids=[])",
            str(missing_project),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
    assert not missing_project.exists()
    assert settings.read_bytes() == original_settings
    assert set(tmp_path.iterdir()) == {settings}

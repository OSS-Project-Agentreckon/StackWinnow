"""Portable selection intent; never a transfer of local state or executable plans."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal

from pydantic import Field, field_validator, model_validator

from stackwinnow.adapters._managed import read_json
from stackwinnow.adapters.graphify import RelationshipExpectation
from stackwinnow.adapters.graphify_index import EXCLUDED
from stackwinnow.catalog import load_catalog
from stackwinnow.contracts import Contract
from stackwinnow.detect import ModelPreference
from stackwinnow.supported import ToolSelection, supported_modes, validate_supported_host
from stackwinnow.workflow import (
    WorkflowPlan,
    WorkflowRequest,
    _checksum,
    plan_workflow,
    recipe_fingerprint,
)


class ProfileError(ValueError):
    """An invalid or incompatible profile needs a new explicit review."""


class PortableRelationship(RelationshipExpectation):
    """Relative source paths and symbol labels, without machine/private locations."""

    @field_validator("caller_file", "callee_file")
    @classmethod
    def portable_source(cls, value: str) -> str:
        path = PurePosixPath(value)
        private = set(EXCLUDED) | {".aws", ".ssh"}
        if (
            PureWindowsPath(value).drive
            or not value.isprintable()
            or len(value) > 512
            or value.startswith("~")
            or any(
                part.casefold() in private
                or part.casefold() == ".env"
                or part.casefold().startswith(".env.")
                for part in path.parts
            )
        ):
            raise ValueError(
                "Use a portable project-relative source path, excluding private state."
            )
        return value

    @field_validator("caller_label", "callee_label")
    @classmethod
    def portable_symbol(cls, value: str) -> str:
        if len(value) > 256 or re.fullmatch(r"[A-Za-z_$][\w.$]*(?:\(\))?", value) is None:
            raise ValueError("Portable relationship labels must be simple qualified symbol names.")
        return value


def _requirements(selections: tuple[ToolSelection, ...]) -> dict[str, tuple[str, ...]]:
    registry = {mode.tool_id: mode.requirements for mode in supported_modes()}
    return {selection.tool_id: registry[selection.tool_id] for selection in selections}


class PortableProfile(Contract):
    """An explicit allowlist; extra fields at every level are rejected."""

    schema_version: Literal[1]
    kind: Literal["stackwinnow-profile"]
    selections: tuple[ToolSelection, ...] = Field(min_length=1, max_length=4)
    assistant: Literal["codex"] = "codex"
    model_preference: ModelPreference = "local"
    requirements: dict[str, tuple[str, ...]]
    expectation: PortableRelationship | None = None

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_schema(cls, value):
        if type(value) is not int:
            raise ValueError("Profile schema_version must be an integer.")
        return value

    @model_validator(mode="after")
    def reviewed_selection(self):
        # Reuse the actual execution request's duplicate/expectation constraints.
        request = self.workflow_request()
        if self.requirements != _requirements(self.selections):
            raise ValueError("Profile requirements differ from the supported-mode registry.")
        catalog = load_catalog()
        selected = set(request.tool_ids)
        if any(selected.intersection(catalog.get(tool_id).conflicts) for tool_id in selected):
            raise ValueError("The selected tools have a declared conflict; review the selection.")
        return self

    def workflow_request(self) -> WorkflowRequest:
        return WorkflowRequest(
            selections=self.selections,
            assistant=self.assistant,
            model_preference=self.model_preference,
            expectation=RelationshipExpectation.model_validate(self.expectation.model_dump())
            if self.expectation is not None
            else None,
        )


def export_profile(plan: WorkflowPlan) -> PortableProfile:
    """Export selection intent without inspecting the former source project."""
    try:
        checked = WorkflowPlan.model_validate(plan.model_dump())
        if _checksum(checked) != checked.checksum or recipe_fingerprint() != checked.recipe_sha256:
            raise ProfileError("Workflow document changed; export from a current reviewed plan.")
        request = checked.request
        return PortableProfile(
            schema_version=1,
            kind="stackwinnow-profile",
            selections=request.selections,
            assistant=request.assistant,
            model_preference=request.model_preference,
            requirements=_requirements(request.selections),
            expectation=PortableRelationship.model_validate(request.expectation.model_dump())
            if request.expectation is not None
            else None,
        )
    except ProfileError:
        raise
    except (OSError, ValueError, RuntimeError) as exc:
        raise ProfileError(
            "Cannot export this selection; check supported modes and portable relationship paths/labels."
        ) from exc


def load_profile(path: str | Path) -> PortableProfile:
    try:
        return PortableProfile.model_validate(read_json(Path(path)))
    except (OSError, ValueError, RuntimeError) as exc:
        # Do not reflect untrusted fields/values (which may contain credentials).
        raise ProfileError(
            "Invalid portable profile; check schema, selections and compatibility."
        ) from exc


def import_profile(profile: PortableProfile, project_root: str | Path) -> WorkflowPlan:
    """Validate intent, then plan against destination state without executing anything."""
    try:
        checked = PortableProfile.model_validate(profile.model_dump())
        request = checked.workflow_request()
    except (OSError, ValueError, RuntimeError) as exc:
        raise ProfileError(
            "Invalid portable profile; check schema, selections and compatibility."
        ) from exc
    plan = plan_workflow(project_root, request)
    try:
        validate_supported_host(request.tool_ids, plan.state.host)
    except ValueError as exc:
        raise ProfileError(str(exc)) from exc
    return plan

"""Data exchanged between discovery, installation, and verification components.

These contracts validate data only. Constructing or importing them never inspects
a project, executes a plan, or establishes that a tool is functional.
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$", max_length=80),
]


class Contract(BaseModel):
    """Reject misspelled fields instead of silently discarding them."""

    model_config = ConfigDict(extra="forbid")


class EvidenceRef(Contract):
    """A document/file reference and the observation it supports."""

    source: NonEmptyText
    detail: NonEmptyText


class ProjectProfile(Contract):
    """User goals and observed project facts, without inferred defaults."""

    schema_version: Literal[1] = 1
    project_root: NonEmptyText
    goals: list[NonEmptyText] = Field(default_factory=list)
    assistant: Identifier | None = None
    operating_system: NonEmptyText | None = None
    facts: dict[NonEmptyText, list[NonEmptyText]] = Field(default_factory=dict)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class IntegrationAvailability(StrEnum):
    """Adapter availability, not proof of compatibility or verification."""

    CATALOG_ONLY = "catalog_only"
    ADAPTER_AVAILABLE = "adapter_available"


class ToolSpec(Contract):
    """Catalog metadata; an unknown license remains explicitly unknown."""

    schema_version: Literal[1] = 1
    tool_id: Identifier
    name: NonEmptyText
    description: NonEmptyText
    repository: HttpUrl
    license: NonEmptyText | None = None
    capabilities: list[NonEmptyText] = Field(default_factory=list)
    availability: IntegrationAvailability = IntegrationAvailability.CATALOG_ONLY
    evidence: list[EvidenceRef] = Field(default_factory=list)


class PlanStep(Contract):
    """An intended step, with no executable command or receipt."""

    step_id: Identifier
    tool_id: Identifier
    description: NonEmptyText


class InstallPlan(Contract):
    """Ordered intentions; execution details and receipts belong to the runtime."""

    schema_version: Literal[1] = 1
    project_root: NonEmptyText
    assistant: Identifier | None = None
    tool_ids: list[Identifier]
    steps: list[PlanStep] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_step_references(self) -> "InstallPlan":
        if len(self.tool_ids) != len(set(self.tool_ids)):
            raise ValueError("tool_ids must be unique")
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("step IDs must be unique")
        selected = set(self.tool_ids)
        for step in self.steps:
            if step.tool_id not in selected:
                raise ValueError(f"step '{step.step_id}' references an unselected tool")
        return self


class OperationStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class OperationResult(Contract):
    """A reported operation outcome; status is always supplied by its producer."""

    schema_version: Literal[1] = 1
    status: OperationStatus
    message: NonEmptyText
    tool_id: Identifier | None = None
    step_id: Identifier | None = None
    errors: list[NonEmptyText] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)

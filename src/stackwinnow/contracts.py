"""Data exchanged between discovery, installation, and verification components.

These contracts validate data only. Constructing or importing them never inspects
a project, executes a plan, or establishes that a tool is functional.
"""

from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    JsonValue,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
# Paths and source references must retain their exact spelling.
UntrimmedText = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$", max_length=80),
]


class Contract(BaseModel):
    """Reject misspelled fields instead of silently discarding them."""

    model_config = ConfigDict(extra="forbid")


class EvidenceRef(Contract):
    """A document/file reference and the observation it supports."""

    source: UntrimmedText
    detail: NonEmptyText


class ProjectProfile(Contract):
    """User goals and observed project facts, without inferred defaults."""

    schema_version: Literal[1] = 1
    project_root: UntrimmedText
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
    project_root: UntrimmedText
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


JsonKeyPath = Annotated[tuple[StrictStr, ...], Field(min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class _ConfigContract(Contract):
    """Configuration data is JSON-only and revalidated by apply before use."""

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)


class JsonConfigEdit(_ConfigContract):
    """Set one object key; replacing a different existing value is explicit."""

    key_path: JsonKeyPath
    value: JsonValue
    replace_existing: StrictBool = False


class ConfigValue(_ConfigContract):
    """A missing key is distinct from a present JSON null."""

    exists: StrictBool
    value: JsonValue = None

    @model_validator(mode="after")
    def validate_absence(self) -> "ConfigValue":
        if not self.exists and self.value is not None:
            raise ValueError("an absent key cannot have a value")
        return self


class ConfigFileState(_ConfigContract):
    """Expected bytes and POSIX permission bits, without storing the whole file."""

    exists: StrictBool
    sha256: Sha256 | None = None
    mode: Annotated[StrictInt, Field(ge=0, le=0o7777)] | None = None

    @model_validator(mode="after")
    def validate_presence(self) -> "ConfigFileState":
        if self.exists:
            if self.sha256 is None or self.mode is None:
                raise ValueError("an existing file requires a digest and permission bits")
        elif self.sha256 is not None or self.mode is not None:
            raise ValueError("an absent file cannot have a digest or permission bits")
        return self


class OwnedConfigEdit(_ConfigContract):
    key_path: JsonKeyPath
    original: ConfigValue
    written: JsonValue


class ConfigPatch(_ConfigContract):
    """Preview data; it becomes ownership evidence only after a reported write."""

    schema_version: Literal[1] = 1
    format: Literal["json"] = "json"
    project_root: StrictStr
    relative_path: StrictStr
    tool_id: Identifier
    expected_file: ConfigFileState
    written_file: ConfigFileState
    edits: tuple[OwnedConfigEdit, ...] = ()
    created_objects: tuple[JsonKeyPath, ...] = ()

    @model_validator(mode="after")
    def validate_paths(self) -> "ConfigPatch":
        if "\x00" in self.project_root or not Path(self.project_root).is_absolute():
            raise ValueError("project_root must be an absolute local path")
        path = PurePosixPath(self.relative_path)
        if (
            not path.parts
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in self.relative_path
            or "\x00" in self.relative_path
            or path.as_posix() != self.relative_path
        ):
            raise ValueError("relative_path must be a normalized project-relative POSIX path")
        paths = [edit.key_path for edit in self.edits]
        for index, key_path in enumerate(paths):
            for other in paths[index + 1 :]:
                shorter = min(len(key_path), len(other))
                if key_path[:shorter] == other[:shorter]:
                    raise ValueError("configuration edits cannot overlap or repeat a key path")
        if len(self.created_objects) != len(set(self.created_objects)):
            raise ValueError("created object paths must be unique")
        return self


class ConfigApplyResult(_ConfigContract):
    """Ownership is returned if publication occurred, including a cleanup failure."""

    schema_version: Literal[1] = 1
    result: OperationResult
    ownership: ConfigPatch | None = None

"""Offline catalog loading and conservative, explainable setup eligibility."""

from datetime import date
from enum import StrEnum
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, HttpUrl, StringConstraints, ValidationError, model_validator

from stackwinnow.contracts import (
    Contract,
    Identifier,
    IntegrationAvailability,
    NonEmptyText,
    OperationStatus,
    ProjectProfile,
    ToolSpec,
)


class Category(StrEnum):
    CONTEXT = "context"
    CACHING = "caching"
    MODEL_GATEWAY = "model-gateway"
    EVALUATION = "evaluation"
    BROWSER_AUTOMATION = "browser-automation"
    OBSERVABILITY = "observability"
    CODING = "coding"
    ORCHESTRATION = "orchestration"
    PROMPT_OPTIMIZATION = "prompt-optimization"


class Platform(StrEnum):
    MACOS = "macos"
    LINUX = "linux"
    WINDOWS = "windows"


# Reviewed license identifiers, not permission to relicense upstream components.
OPEN_SOURCE_LICENSES = frozenset(
    {
        "MIT",
        "Apache-2.0",
        "GPL-3.0-or-later",
        "GPL-3.0-only",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "ISC",
        "MPL-2.0",
        "LGPL-3.0-or-later",
    }
)


class ReviewedSource(Contract):
    kind: Literal["readme", "license", "requirements"]
    url: HttpUrl
    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class CatalogEntry(ToolSpec):
    """Extend catalog metadata without changing the shared bootstrap contracts."""

    category: Category
    prerequisites: list[NonEmptyText] = Field(min_length=1)
    compatibility_notes: NonEmptyText
    supported_platforms: list[Platform] = Field(default_factory=list)
    supported_assistants: list[Identifier] = Field(default_factory=list)
    limitations: list[NonEmptyText] = Field(min_length=1)
    conflicts: list[Identifier] = Field(default_factory=list)
    alternatives: list[Identifier] = Field(default_factory=list)
    reviewed_on: date
    license_review: Literal["reviewed", "unresolved"] = "unresolved"
    license_scope: NonEmptyText
    sources: list[ReviewedSource] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_review(self) -> "CatalogEntry":
        kinds = {source.kind for source in self.sources}
        if "readme" not in kinds:
            raise ValueError("a reviewed README source is required")
        if self.license_review == "reviewed":
            if self.license not in OPEN_SOURCE_LICENSES or "license" not in kinds:
                raise ValueError("reviewed licenses require a recognized OSS ID and license source")
        for field in ("conflicts", "alternatives", "supported_platforms", "supported_assistants"):
            values = getattr(self, field)
            if len(values) != len(set(values)):
                raise ValueError(f"{field} must contain unique values")
        return self


class Catalog(Contract):
    schema_version: Literal[1] = 1
    tools: list[CatalogEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> "Catalog":
        ids = {tool.tool_id for tool in self.tools}
        if len(ids) != len(self.tools):
            raise ValueError("catalog tool IDs must be unique")
        for tool in self.tools:
            for related in [*tool.conflicts, *tool.alternatives]:
                if related == tool.tool_id or related not in ids:
                    raise ValueError(f"{tool.tool_id}: invalid related tool reference '{related}'")
        return self

    def get(self, tool_id: str) -> CatalogEntry:
        for tool in self.tools:
            if tool.tool_id == tool_id:
                return tool
        raise KeyError(tool_id)


class CatalogError(ValueError):
    """The catalog resource is missing or invalid."""


def load_catalog(path: Path | None = None) -> Catalog:
    """Load the packaged resource, or a supplied local file; never use the network."""
    source = path if path is not None else files("stackwinnow").joinpath("data/catalog.json")
    try:
        return Catalog.model_validate_json(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise CatalogError(f"Cannot load catalog from {source}: {exc}") from exc


class EligibilityContext(Contract):
    """Runtime-supplied observations. The CLI does not fabricate readiness checks."""

    platform: Platform | None = None
    assistant: Identifier | None = None
    registered_adapters: list[Identifier] = Field(default_factory=list)
    prerequisite_checks: dict[Identifier, OperationStatus] = Field(default_factory=dict)
    selected_tools: list[Identifier] = Field(default_factory=list)

    @classmethod
    def from_profile(cls, profile: ProjectProfile) -> "EligibilityContext":
        os_values = profile.facts.get("os", [])
        name = os_values[0] if os_values else profile.operating_system
        aliases = {
            "darwin": Platform.MACOS,
            "macos": Platform.MACOS,
            "linux": Platform.LINUX,
            "windows": Platform.WINDOWS,
        }
        return cls(
            platform=aliases.get(name.lower()) if name else None, assistant=profile.assistant
        )


class EligibilityReason(Contract):
    code: Identifier
    message: NonEmptyText


class Eligibility(Contract):
    installable: bool
    reasons: list[EligibilityReason]


def evaluate_eligibility(
    tool: CatalogEntry, context: EligibilityContext | None = None
) -> Eligibility:
    """Check catalog/setup gates, not functional verification or artifact licensing."""
    context = context or EligibilityContext()
    reasons: list[EligibilityReason] = []

    def block(code: str, message: str) -> None:
        reasons.append(EligibilityReason(code=code, message=message))

    if tool.license_review != "reviewed" or tool.license not in OPEN_SOURCE_LICENSES:
        block("license-unresolved", "The open-source license scope has not been resolved.")
    if tool.availability != IntegrationAvailability.ADAPTER_AVAILABLE:
        block("adapter-unavailable", "Catalog only: no StackWinnow adapter is available.")
    elif tool.tool_id not in context.registered_adapters:
        block("adapter-unregistered", "The declared adapter is not registered in this runtime.")
    if context.platform is None:
        block("platform-unknown", "A target operating system has not been supplied.")
    elif not tool.supported_platforms:
        block("platform-unverified", "Platform compatibility is not documented in this entry.")
    elif context.platform not in tool.supported_platforms:
        block("platform-unsupported", f"This entry does not support {context.platform}.")
    if context.assistant is None:
        block("assistant-unknown", "A target coding assistant has not been supplied.")
    elif not tool.supported_assistants:
        block("assistant-unverified", "Assistant compatibility is not documented in this entry.")
    elif context.assistant not in tool.supported_assistants:
        block("assistant-unsupported", f"This entry does not support {context.assistant}.")
    check = context.prerequisite_checks.get(tool.tool_id)
    if check != OperationStatus.SUCCEEDED:
        if check in (OperationStatus.FAILED, OperationStatus.BLOCKED):
            block("prerequisites-failed", "The runtime prerequisite check failed or was blocked.")
        else:
            block("prerequisites-unverified", "Tool-specific prerequisites have not been checked.")
    for conflict in sorted(set(tool.conflicts) & set(context.selected_tools)):
        block("selection-conflict", f"This tool conflicts with selected tool '{conflict}'.")
    return Eligibility(installable=not reasons, reasons=reasons)


def filter_catalog(
    catalog: Catalog,
    *,
    category: Category | None = None,
    installable_only: bool = False,
    context: EligibilityContext | None = None,
) -> list[CatalogEntry]:
    return [
        tool
        for tool in sorted(catalog.tools, key=lambda tool: tool.tool_id)
        if (category is None or tool.category == category)
        and (not installable_only or evaluate_eligibility(tool, context).installable)
    ]

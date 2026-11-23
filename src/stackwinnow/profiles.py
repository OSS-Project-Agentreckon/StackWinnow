"""Export and import portable project profiles.

A portable profile captures the reproducible parts of a project's tool setup —
the explicit goals, assistant, model preference, and selected tools, plus
catalog-derived compatibility metadata. It deliberately excludes machine-specific
state: no project path, no observed dependency facts, no evidence, no diagnostics,
and no credentials. This keeps an exported profile safe to share and re-plannable
in a different project.

Exporting and importing validate data only. They run offline, make no model
calls, install nothing, and never write to the inspected project.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from stackwinnow import __version__
from stackwinnow.catalog import Catalog, Category, Platform, load_catalog
from stackwinnow.contracts import (
    Contract,
    Identifier,
    IntegrationAvailability,
    NonEmptyText,
)
from stackwinnow.detect import InspectionResult, ModelPreference, inspect_project
from stackwinnow.recommend import RecommendationResult, recommend_tools


class ProfileError(Exception):
    """A profile could not be built, parsed, or validated."""


class ProfileToolEntry(Contract):
    """A selected tool and the catalog metadata needed to re-plan it elsewhere."""

    tool_id: Identifier
    name: NonEmptyText
    category: Category
    license: NonEmptyText | None = None
    availability: IntegrationAvailability = IntegrationAvailability.CATALOG_ONLY
    # Recorded only when a tested version is supplied; never invented or measured.
    version: NonEmptyText | None = None
    supported_platforms: list[Platform] = Field(default_factory=list)
    supported_assistants: list[Identifier] = Field(default_factory=list)


class PortableProfile(Contract):
    """A shareable, re-plannable record of project selections and intent.

    Intentionally omits ``project_root``, observed ``facts``, ``evidence``, and
    ``diagnostics`` so private paths, dependency observations, and secrets cannot
    enter the artifact.
    """

    schema_version: Literal[1] = 1
    stackwinnow_version: NonEmptyText
    goals: list[NonEmptyText] = Field(default_factory=list)
    assistant: Identifier | None = None
    model_preference: ModelPreference | None = None
    target_platform: Platform | None = None
    tools: list[ProfileToolEntry] = Field(default_factory=list)
    notes: list[NonEmptyText] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_tools(self) -> "PortableProfile":
        seen = [entry.tool_id for entry in self.tools]
        if len(seen) != len(set(seen)):
            raise ValueError("Profile tool IDs must be unique.")
        return self


def export_profile(
    inspection: InspectionResult,
    *,
    catalog: Catalog | None = None,
    platform: Platform | None = None,
    tool_versions: Mapping[str, str] | None = None,
    stackwinnow_version: str = __version__,
) -> PortableProfile:
    """Build a portable profile from an inspection's explicit selections and intent.

    Only the user's declared goals/assistant/preference and explicitly selected
    tools are carried over. Each selected tool is resolved against the catalog for
    its name, category, license, availability, and documented compatibility. A
    per-tool ``version`` is recorded only when supplied in ``tool_versions``.

    Raises :class:`ProfileError` if a selected tool is absent from the catalog.
    """
    resolved = catalog if catalog is not None else load_catalog()
    tools: list[ProfileToolEntry] = []
    for tool_id in inspection.selected_tools:
        try:
            entry = resolved.get(tool_id)
        except KeyError as exc:
            raise ProfileError(f"Selected tool '{tool_id}' is not in the catalog.") from exc
        version = tool_versions.get(tool_id) if tool_versions else None
        tools.append(
            ProfileToolEntry(
                tool_id=entry.tool_id,
                name=entry.name,
                category=entry.category,
                license=entry.license,
                availability=entry.availability,
                version=version,
                supported_platforms=list(entry.supported_platforms),
                supported_assistants=list(entry.supported_assistants),
            )
        )
    return PortableProfile(
        stackwinnow_version=stackwinnow_version,
        goals=list(inspection.profile.goals),
        assistant=inspection.profile.assistant,
        model_preference=inspection.model_preference,
        target_platform=platform,
        tools=tools,
    )


def import_profile(text: str | bytes) -> PortableProfile:
    """Parse and validate portable-profile JSON.

    Raises :class:`ProfileError` for malformed or incompatible input. The message
    is fixed and does not echo arbitrary file contents.
    """
    try:
        return PortableProfile.model_validate_json(text)
    except ValidationError as exc:
        raise ProfileError("Profile is malformed or uses an unsupported schema version.") from exc


def replan_profile(
    profile: PortableProfile,
    project_root: Path | str,
    *,
    catalog: Catalog | None = None,
    platform: Platform | None = None,
) -> RecommendationResult:
    """Apply a portable profile's intent to a project and return a fresh plan.

    Inspects ``project_root`` with the profile's goals, assistant, selected tools,
    and model preference, then produces recommendations for that project. An
    explicit ``platform`` overrides the profile's recorded ``target_platform``.

    Propagates :class:`stackwinnow.detect.InspectionError` and
    :class:`stackwinnow.recommend.RecommendationError` for an invalid project or a
    tool missing from the catalog.
    """
    resolved = catalog if catalog is not None else load_catalog()
    inspection = inspect_project(
        project_root,
        goals=list(profile.goals),
        assistant=profile.assistant,
        selected_tools=[entry.tool_id for entry in profile.tools],
        model_preference=profile.model_preference,
        catalog=resolved,
    )
    return recommend_tools(
        inspection,
        catalog=resolved,
        platform=platform if platform is not None else profile.target_platform,
    )


__all__ = [
    "PortableProfile",
    "ProfileError",
    "ProfileToolEntry",
    "export_profile",
    "import_profile",
    "replan_profile",
]

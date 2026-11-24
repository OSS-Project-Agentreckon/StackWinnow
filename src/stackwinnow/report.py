"""Compose a read-only project report from inspection, recommendation and checks.

`build_report` runs the existing offline pipeline — project inspection, explainable
recommendations, optional passive verification, and catalog eligibility — and
returns a `ProjectReport`. The report renders to Markdown (a shareable document)
or to a structured JSON payload. Building a report installs nothing, runs no
project scripts, makes no model calls, and writes nothing; verification is passive
unless a caller opts into a fresh functional check elsewhere.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from stackwinnow.catalog import Catalog, load_catalog
from stackwinnow.contracts import Contract, NonEmptyText
from stackwinnow.detect import ModelPreference, inspect_project
from stackwinnow.recommend import RecommendationResult, recommend_tools
from stackwinnow.verify import check_project
from stackwinnow.verify.models import VerificationReport


class ReportError(ValueError):
    """A report could not be assembled from the requested inputs."""


class ProjectReport(Contract):
    """An inspection + recommendation snapshot, with optional passive verification.

    Self-contained and round-trippable: it embeds the recommendation (which embeds
    the inspection) and, when requested, a verification report. Readiness and
    completeness are derived, never caller-supplied.
    """

    schema_version: Literal[1] = 1
    generated_at: NonEmptyText
    recommendation: RecommendationResult
    verification: VerificationReport | None = None

    @property
    def project_root(self) -> str:
        return self.recommendation.inspection.profile.project_root

    @property
    def ready(self) -> bool:
        complete = self.recommendation.complete
        return complete and (self.verification is None or self.verification.ready)

    def to_payload(self) -> dict:
        """JSON view with exactly one envelope ``schema_version`` and derived flags."""
        recommendation = self.recommendation.model_dump(
            mode="json",
            exclude={
                "schema_version": True,
                "inspection": {
                    "schema_version": True,
                    "profile": {"schema_version"},
                    "diagnostics": {"__all__": {"schema_version"}},
                },
            },
        )
        recommendation["complete"] = self.recommendation.complete
        payload: dict = {
            "schema_version": 1,
            "project_root": self.project_root,
            "generated_at": self.generated_at,
            "ready": self.ready,
            "recommendation": recommendation,
            "verification": None,
        }
        if self.verification is not None:
            verification = self.verification.as_payload()
            verification.pop("schema_version", None)
            payload["verification"] = verification
        return payload

    def to_markdown(self) -> str:
        """Render a shareable Markdown document. Deterministic for a given timestamp."""
        inspection = self.recommendation.inspection
        profile = inspection.profile
        lines: list[str] = [
            f"# StackWinnow report: {self.project_root}",
            "",
            f"_Generated {self.generated_at}. Read-only: no tools were installed, "
            "configured, or run._",
            "",
            "## Project",
            "",
            f"- Inspection: {'complete' if inspection.complete else 'incomplete'}",
            f"- Assistant: {profile.assistant or 'unknown'}",
            f"- Goals: {'; '.join(profile.goals) or 'not supplied'}",
            f"- Model preference: {inspection.model_preference or 'not supplied'}",
            f"- Target platform: {self.recommendation.target_platform or 'unknown'}",
            "",
        ]
        if profile.facts:
            lines += ["| Fact | Values |", "| --- | --- |"]
            for key, values in sorted(profile.facts.items()):
                rendered = ", ".join(values) if values else "(explicitly empty)"
                lines.append(f"| {key} | {rendered} |")
            lines.append("")
        else:
            lines += ["No supported declarations were found; project details remain unknown.", ""]
        if inspection.diagnostics:
            lines.append("Diagnostics:")
            lines += [f"- [{item.status}] {item.message}" for item in inspection.diagnostics]
            lines.append("")

        lines += ["## Recommended tools", ""]
        if not self.recommendation.recommendations:
            lines += ["No tools matched the declared goals and selections.", ""]
        for item in self.recommendation.recommendations:
            label = (
                "selected"
                if item.selected
                else "declared"
                if item.already_declared
                else "goal match"
            )
            lines += [f"### {item.name} (`{item.tool_id}`) — {label}", "", item.description, ""]
            for reason in item.reasons:
                detail = (
                    f"{reason.fact_key}: {', '.join(reason.values)}"
                    if reason.fact_key
                    else "; ".join(reason.goals)
                )
                suffix = f" ({detail})" if detail else ""
                lines.append(f"- Why: {reason.message}{suffix}")
                if reason.matched_capabilities:
                    lines.append(
                        f"  - Matched capabilities: {', '.join(reason.matched_capabilities)}"
                    )
            setup = "eligible" if item.eligibility.installable else "unavailable"
            lines.append(f"- Setup readiness: {setup}")
            lines += [f"  - {reason.message}" for reason in item.eligibility.reasons]
            lines.append(f"- Integration: {_integration_status(item)}")
            if item.alternatives:
                lines.append(f"- Alternatives to compare: {', '.join(item.alternatives)}")
            if item.conflicts_with:
                lines.append(f"- Conflicts with: {', '.join(item.conflicts_with)}")
            lines += [f"- Limitation: {limitation}" for limitation in item.limitations]
            lines.append("")

        if self.recommendation.relationships:
            lines += ["## Relationships", ""]
            lines += [
                f"- {relationship.kind}: {' / '.join(relationship.tools)}"
                for relationship in self.recommendation.relationships
            ]
            lines.append("")
        if self.recommendation.unmatched_goals:
            lines += ["## Unmatched goals", ""]
            lines += [f"- {goal}" for goal in self.recommendation.unmatched_goals]
            lines.append("")
        if self.recommendation.notes:
            lines += ["## Notes", ""]
            lines += [f"- {note}" for note in self.recommendation.notes]
            lines.append("")

        if self.verification is not None:
            lines += ["## Verification", ""]
            lines.append(
                f"Passive check (functional checks "
                f"{'ran' if self.verification.run_functional else 'did not run'}); "
                f"overall: {self.verification.status}."
            )
            for tool in self.verification.tools:
                lines.append(f"### {tool.tool_id} — {tool.status}")
                lines += [
                    f"- [{check.status}] {check.kind}: {check.message}" for check in tool.checks
                ]
                lines.append("")

        lines += [
            "## Caveats",
            "",
            "Catalog membership is not installation readiness; a recommendation is not an "
            "executable plan; a tool is not proven functional without a fresh check.",
        ]
        return "\n".join(lines) + "\n"


def _integration_status(recommendation) -> str:
    """Describe adapter availability using eligibility reason codes already present."""
    codes = {reason.code for reason in recommendation.eligibility.reasons}
    if "adapter-unavailable" in codes:
        return "catalog only (no StackWinnow adapter)"
    if "adapter-unregistered" in codes:
        return "adapter available, not registered in this runtime"
    return "adapter available"


def build_report(
    project_root: Path | str,
    *,
    goals: list[str] | None = None,
    assistant: str | None = None,
    selected_tools: list[str] | None = None,
    model_preference: ModelPreference | None = None,
    config_path: str | None = None,
    platform: str | None = None,
    include_verification: bool = False,
    generated_at: str | None = None,
    catalog: Catalog | None = None,
) -> ProjectReport:
    """Assemble a read-only project report.

    Inspects the project, explains recommendations, and — when
    ``include_verification`` is set — reads passive verification state for the
    selected tools (no commands or writes). ``include_verification`` requires at
    least one selected tool. Propagates ``InspectionError``/``RecommendationError``/
    ``CatalogError``/``VerificationError`` for invalid inputs and raises
    ``ReportError`` when verification is requested without a tool selection.
    """
    resolved = catalog if catalog is not None else load_catalog()
    inspection = inspect_project(
        project_root,
        goals=goals,
        assistant=assistant,
        selected_tools=selected_tools,
        model_preference=model_preference,
        config_path=config_path,
        catalog=resolved,
    )
    recommendation = recommend_tools(inspection, catalog=resolved, platform=platform)
    verification: VerificationReport | None = None
    if include_verification:
        if not inspection.selected_tools:
            raise ReportError("Verification needs at least one selected tool. Use --tool.")
        verification = check_project(
            project_root, tool_ids=inspection.selected_tools, run_functional=False
        )
    return ProjectReport(
        generated_at=generated_at or datetime.now(UTC).isoformat(),
        recommendation=recommendation,
        verification=verification,
    )


__all__ = ["ProjectReport", "ReportError", "build_report"]

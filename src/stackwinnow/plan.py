"""Read-only preliminary checks for legacy generic installation plans.

This plan has no authoritative adapter recipe. Receipts, environment directories
and PATH entries are observations, not installation or health evidence. Existing
state requires a fresh dedicated workflow review. No commands or writes occur.
"""

from __future__ import annotations

import platform
import shutil
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field

from stackwinnow.adapters._managed import directories, record_for
from stackwinnow.catalog import Catalog, EligibilityContext, evaluate_eligibility, load_catalog
from stackwinnow.contracts import (
    Contract,
    Identifier,
    InstallPlan,
    NonEmptyText,
    PlanStep,
    UntrimmedText,
)
from stackwinnow.installer import ExecutionRecord

_MANAGED_ROOT = ".stackwinnow"


class PreflightStatus(StrEnum):
    """Outcome of a preliminary step check; old receipt statuses remain readable."""

    READY = "ready"
    BLOCKED = "blocked"
    SKIP_ALREADY_MANAGED = "skip-already-managed"
    EXTERNAL_INSTALL_DETECTED = "external-install-detected"
    STALE_RECEIPT = "stale-receipt"


class PreflightCheck(Contract):
    """Pre-flight result for one plan step."""

    step_id: Identifier
    tool_id: Identifier
    status: PreflightStatus
    message: NonEmptyText
    reasons: list[NonEmptyText] = Field(default_factory=list)
    external_path: str | None = None


class PreflightReport(Contract):
    """Aggregated pre-flight results for every step in a plan."""

    schema_version: Literal[1] = 1
    project_root: UntrimmedText
    checks: list[PreflightCheck] = Field(default_factory=list)

    @property
    def is_ready_to_apply(self) -> bool:
        """True only for a nonempty set of preliminary READY checks.

        This is not execution approval: a reviewed adapter/workflow plan must
        validate the recipe, runtime, ownership and functional work. Legacy
        skip/external statuses never grant readiness.
        """
        return bool(self.checks) and all(c.status == PreflightStatus.READY for c in self.checks)

    @property
    def blocked_checks(self) -> list[PreflightCheck]:
        return [c for c in self.checks if c.status == PreflightStatus.BLOCKED]


class PreflightError(Exception):
    """Raised when pre-flight cannot safely inspect existing state."""


def _has_managed_env(project_root: str, tool_id: str) -> bool:
    """Observe an occupied tool environment path; never establish ownership.

    Reject unsafe ancestors even when the final Python/Node directory is real.
    Any occupied tool root requires adapter review, including incomplete installs.
    """
    path = directories(Path(project_root), f"{_MANAGED_ROOT}/envs/{tool_id}")
    for runtime in ("python", "node"):
        directories(Path(project_root), f"{_MANAGED_ROOT}/envs/{tool_id}/{runtime}")
    return path.exists()


def _find_external_executable(project_root: str, tool_id: str) -> str | None:
    """Observe a PATH entry outside the managed root, without running it."""
    path = shutil.which(tool_id)
    if path is None:
        return None
    managed_root = (Path(project_root) / _MANAGED_ROOT).resolve()
    if Path(path).resolve().is_relative_to(managed_root):
        return None
    return path


def _check_step(
    step: PlanStep,
    plan: InstallPlan,
    catalog: Catalog,
    context: EligibilityContext,
    record: ExecutionRecord,
    occupied: set[str],
) -> PreflightCheck:
    try:
        entry = catalog.get(step.tool_id)
    except KeyError:
        return PreflightCheck(
            step_id=step.step_id,
            tool_id=step.tool_id,
            status=PreflightStatus.BLOCKED,
            message=f"Tool '{step.tool_id}' is not in the catalog.",
            reasons=["Use 'workflow modes' to select a supported executable tool."],
        )

    # Eligibility precedes observations of prior/external installations.
    check_context = context.model_copy(update={"selected_tools": list(plan.tool_ids)})
    eligibility = evaluate_eligibility(entry, check_context)
    if not eligibility.installable:
        return PreflightCheck(
            step_id=step.step_id,
            tool_id=step.tool_id,
            status=PreflightStatus.BLOCKED,
            message=f"'{step.tool_id}' is not eligible for installation.",
            reasons=[r.message for r in eligibility.reasons],
        )

    # Lazy import: Graphify's legacy preview depends on this module.
    from stackwinnow.supported import supported_modes, validate_supported_host

    mode = next((mode for mode in supported_modes() if mode.tool_id == step.tool_id), None)
    if mode is None:
        return PreflightCheck(
            step_id=step.step_id,
            tool_id=step.tool_id,
            status=PreflightStatus.BLOCKED,
            message=f"'{step.tool_id}' has no supported executable mode.",
            reasons=["Use 'workflow modes' to select a supported tool."],
        )
    if context.platform != "macos":
        return PreflightCheck(
            step_id=step.step_id,
            tool_id=step.tool_id,
            status=PreflightStatus.BLOCKED,
            message=f"'{step.tool_id}' targets a platform outside the supported local modes.",
            reasons=["The current executable modes require a macOS target and macOS arm64 host."],
        )
    if (plan.assistant is not None and plan.assistant != context.assistant) or (
        mode.mode == "codex" and (context.assistant != "codex" or plan.assistant != "codex")
    ):
        return PreflightCheck(
            step_id=step.step_id,
            tool_id=step.tool_id,
            status=PreflightStatus.BLOCKED,
            message=f"'{step.tool_id}' has no matching assistant selection for this mode.",
            reasons=["Plan and context must agree; Codex modes require an explicit Codex plan."],
        )
    try:
        validate_supported_host(
            [step.tool_id],
            (
                platform.system(),
                platform.machine(),
                platform.python_implementation(),
                platform.python_version(),
                platform.mac_ver()[0],
            ),
        )
    except ValueError as exc:
        return PreflightCheck(
            step_id=step.step_id,
            tool_id=step.tool_id,
            status=PreflightStatus.BLOCKED,
            message=f"'{step.tool_id}' cannot execute on this host.",
            reasons=[str(exc)],
        )

    history = any(r.tool_id == step.tool_id for r in record.steps)
    if history or step.tool_id in occupied:
        return PreflightCheck(
            step_id=step.step_id,
            tool_id=step.tool_id,
            status=PreflightStatus.BLOCKED,
            message=f"'{step.tool_id}' has existing state requiring workflow review.",
            reasons=[
                "A receipt or environment directory does not establish a working installation. "
                "Use 'workflow status' and create a fresh 'workflow plan'. "
                "Use reviewed removal or retirement for recovery; preserve receipts."
            ],
        )

    external_path = _find_external_executable(plan.project_root, step.tool_id)
    if external_path is not None:
        return PreflightCheck(
            step_id=step.step_id,
            tool_id=step.tool_id,
            status=PreflightStatus.EXTERNAL_INSTALL_DETECTED,
            message=f"'{step.tool_id}' has a PATH executable at {external_path!r}.",
            reasons=[
                "PATH presence proves neither ownership nor functionality. "
                "Create a fresh 'workflow plan' for the isolated supported mode."
            ],
            external_path=external_path,
        )

    return PreflightCheck(
        step_id=step.step_id,
        tool_id=step.tool_id,
        status=PreflightStatus.READY,
        message=f"'{step.tool_id}' passed preliminary eligibility checks.",
        reasons=["Use a reviewed 'workflow plan' to validate the recipe before execution."],
    )


def check_plan(
    plan: InstallPlan,
    *,
    catalog: Catalog | None = None,
    context: EligibilityContext | None = None,
) -> PreflightReport:
    """Check all steps without commands or writes.

    Reads bounded receipts and guarded environment paths. Raises PreflightError
    on unsafe, corrupt or mismatched state. Existing state requires dedicated
    workflow review, never generic skip/replay or receipt deletion.
    """
    catalog = catalog or load_catalog()
    context = context or EligibilityContext()
    try:
        record = record_for(Path(plan.project_root))
        # Guard paths even for ineligible steps or steps with existing history.
        occupied = {tid for tid in plan.tool_ids if _has_managed_env(plan.project_root, tid)}
        checks = [
            _check_step(step, plan, catalog, context, record, occupied) for step in plan.steps
        ]
    except (OSError, ValueError) as exc:
        raise PreflightError(f"Cannot inspect managed state safely: {exc}") from exc

    return PreflightReport(project_root=plan.project_root, checks=checks)

"""Pre-flight plan validation and existing-installation detection.

Pre-flight runs before any install step and before any filesystem writes.
It is read-only: it may inspect existing directories and PATH but never
creates, modifies, or deletes anything.

Three separate concerns are checked for every plan step:

1. Eligibility — does the catalog license and platform allow installation?
2. Existing managed install — does StackWinnow already own this tool here?
3. External install — is the tool present in the system outside our control?

A stale receipt (succeeded but environment is gone) is surfaced separately so
the caller can decide whether to reinstate or wipe state before retrying.
"""

from __future__ import annotations

import shutil
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field

from stackwinnow.catalog import OPEN_SOURCE_LICENSES, Catalog, EligibilityContext, load_catalog
from stackwinnow.contracts import (
    Contract,
    Identifier,
    InstallPlan,
    NonEmptyText,
    PlanStep,
    UntrimmedText,
)
from stackwinnow.installer import ExecutionRecord, InstallerError, load_record

# Path layout for managed tool environments.  These mirror the constants in
# environments.py (from the runtime step); they are reproduced here to keep
# the plan preflight independent of that unmerged module.
_MANAGED_ROOT = ".stackwinnow"
_ENVS_SUBDIR = "envs"
_PYTHON_SUBDIR = "python"
_NODE_SUBDIR = "node"


class PreflightStatus(StrEnum):
    """Outcome of a single pre-flight step check."""

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
        """True when no step is blocked or stale.

        SKIP_ALREADY_MANAGED and EXTERNAL_INSTALL_DETECTED steps do not block
        apply; the caller decides whether to proceed with them.
        """
        return not any(
            c.status in (PreflightStatus.BLOCKED, PreflightStatus.STALE_RECEIPT)
            for c in self.checks
        )

    @property
    def blocked_checks(self) -> list[PreflightCheck]:
        return [c for c in self.checks if c.status == PreflightStatus.BLOCKED]


class PreflightError(Exception):
    """Raised when pre-flight cannot complete due to corrupt or mismatched state."""


def _has_managed_env(project_root: str, tool_id: str) -> bool:
    """True if a managed Python venv or Node prefix directory exists for this tool."""
    root = Path(project_root) / _MANAGED_ROOT / _ENVS_SUBDIR / tool_id
    return (root / _PYTHON_SUBDIR).exists() or (root / _NODE_SUBDIR).exists()


def _find_external_executable(project_root: str, tool_id: str) -> str | None:
    """Return the absolute PATH to tool_id if found outside the managed root.

    Returns None when the tool is not on PATH at all, or when it is found
    inside our managed .stackwinnow/ directory (indicating a prior StackWinnow
    install is on PATH, not a truly external one).
    """
    path = shutil.which(tool_id)
    if path is None:
        return None
    managed_root = str(Path(project_root).resolve() / ".stackwinnow")
    if str(Path(path).resolve()).startswith(managed_root):
        return None
    return path


def _check_step(
    step: PlanStep,
    plan: InstallPlan,
    catalog: Catalog,
    context: EligibilityContext,
    record: ExecutionRecord | None,
) -> PreflightCheck:
    # 1. Catalog lookup — the tool must exist before any other check.
    try:
        entry = catalog.get(step.tool_id)
    except KeyError:
        return PreflightCheck(
            step_id=step.step_id,
            tool_id=step.tool_id,
            status=PreflightStatus.BLOCKED,
            message=f"Tool '{step.tool_id}' is not in the catalog.",
            reasons=[f"Add '{step.tool_id}' to the catalog before creating a plan for it."],
        )

    # 2. License scope — only tools with a reviewed open-source license may be installed.
    if entry.license_review != "reviewed" or entry.license not in OPEN_SOURCE_LICENSES:
        return PreflightCheck(
            step_id=step.step_id,
            tool_id=step.tool_id,
            status=PreflightStatus.BLOCKED,
            message=f"'{step.tool_id}' has an unresolved or non-OSS license scope.",
            reasons=["Only tools with a reviewed open-source license may be installed."],
        )

    # 3. Platform compatibility — only blocked when platforms are explicitly declared
    #    and the current one is absent; an empty list means "unverified", not "unsupported".
    if context.platform is not None and entry.supported_platforms:
        if context.platform not in entry.supported_platforms:
            return PreflightCheck(
                step_id=step.step_id,
                tool_id=step.tool_id,
                status=PreflightStatus.BLOCKED,
                message=f"'{step.tool_id}' is not supported on {context.platform}.",
                reasons=[
                    f"Supported platforms: {', '.join(str(p) for p in entry.supported_platforms)}."
                ],
            )

    # 4. Stale receipt: receipt says succeeded but the managed environment is gone.
    if record is not None and record.is_succeeded(step.step_id, step.tool_id):
        if not _has_managed_env(plan.project_root, step.tool_id):
            return PreflightCheck(
                step_id=step.step_id,
                tool_id=step.tool_id,
                status=PreflightStatus.STALE_RECEIPT,
                message=(
                    f"Receipt records '{step.tool_id}' as installed "
                    "but the managed environment is missing."
                ),
                reasons=[
                    "The installation may have been deleted outside StackWinnow. "
                    "Re-run apply to reinstall or clear the receipt to start fresh."
                ],
            )
        # Managed env exists and receipt says succeeded — nothing to do for this step.
        return PreflightCheck(
            step_id=step.step_id,
            tool_id=step.tool_id,
            status=PreflightStatus.SKIP_ALREADY_MANAGED,
            message=f"'{step.tool_id}' is already installed and owned by StackWinnow.",
        )

    # 5. External installation — note it without blocking; StackWinnow will not take
    #    ownership of an installation it did not create.
    external_path = _find_external_executable(plan.project_root, step.tool_id)
    if external_path is not None:
        return PreflightCheck(
            step_id=step.step_id,
            tool_id=step.tool_id,
            status=PreflightStatus.EXTERNAL_INSTALL_DETECTED,
            message=(
                f"'{step.tool_id}' is already installed at {external_path!r} "
                "outside StackWinnow's managed environment."
            ),
            reasons=["StackWinnow will not take ownership of an external installation."],
            external_path=external_path,
        )

    # 6. All checks passed.
    return PreflightCheck(
        step_id=step.step_id,
        tool_id=step.tool_id,
        status=PreflightStatus.READY,
        message=f"'{step.tool_id}' is eligible and not currently installed.",
    )


def check_plan(
    plan: InstallPlan,
    *,
    catalog: Catalog | None = None,
    context: EligibilityContext | None = None,
) -> PreflightReport:
    """Check all steps in plan before any filesystem writes.

    Loads the execution record to detect managed and stale installations.
    Raises PreflightError when durable installation receipts are corrupt or
    belong to a different project root; the caller must resolve the conflict
    before retrying.
    """
    catalog = catalog or load_catalog()
    context = context or EligibilityContext()

    try:
        record = load_record(plan.project_root)
    except InstallerError as exc:
        raise PreflightError(str(exc)) from exc

    checks = [_check_step(step, plan, catalog, context, record) for step in plan.steps]
    return PreflightReport(project_root=plan.project_root, checks=checks)

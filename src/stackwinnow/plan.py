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

from stackwinnow.catalog import Catalog, EligibilityContext, evaluate_eligibility, load_catalog
from stackwinnow.contracts import (
    Contract,
    Identifier,
    InstallPlan,
    NonEmptyText,
    OperationStatus,
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
    """True if a real (non-symlink) managed Python venv or Node prefix directory exists."""
    root = Path(project_root) / _MANAGED_ROOT / _ENVS_SUBDIR / tool_id
    py_path = root / _PYTHON_SUBDIR
    node_path = root / _NODE_SUBDIR
    return (py_path.is_dir() and not py_path.is_symlink()) or (
        node_path.is_dir() and not node_path.is_symlink()
    )


def _find_external_executable(project_root: str, tool_id: str) -> str | None:
    """Return the absolute PATH to tool_id if found outside the managed root.

    Returns None when the tool is not on PATH at all, or when it is found
    inside our managed .stackwinnow/ directory (indicating a prior StackWinnow
    install is on PATH, not a truly external one).
    """
    path = shutil.which(tool_id)
    if path is None:
        return None
    managed_root = (Path(project_root) / _MANAGED_ROOT).resolve()
    if Path(path).resolve().is_relative_to(managed_root):
        return None
    return path


def _has_succeeded_tool_receipt(record: ExecutionRecord, tool_id: str) -> bool:
    """True if any real (non-dry-run) step for tool_id succeeded in a prior run."""
    return any(
        r.tool_id == tool_id and r.status == OperationStatus.SUCCEEDED and not r.dry_run
        for r in record.steps
    )


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

    # 2. Tool-level stale/skip detection — checked before eligibility so that existing
    #    managed installations are always surfaced, even if eligibility has changed.
    if record is not None and _has_succeeded_tool_receipt(record, step.tool_id):
        if _has_managed_env(plan.project_root, step.tool_id):
            return PreflightCheck(
                step_id=step.step_id,
                tool_id=step.tool_id,
                status=PreflightStatus.SKIP_ALREADY_MANAGED,
                message=f"'{step.tool_id}' is already installed and owned by StackWinnow.",
            )
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

    # 3. External installation — note it without blocking; StackWinnow will not take
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

    # 4. Full eligibility — reuse shared gates (adapter, platform, assistant, prerequisites,
    #    conflicts). Merge the plan's tool_ids for conflict detection across all selections.
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

    # 5. All checks passed.
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

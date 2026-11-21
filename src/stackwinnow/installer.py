"""Execute installation plans and persist durable step receipts.

Receipts are written after each step so interrupted runs leave the project
in an understandable state. Dry runs never touch the filesystem.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from stackwinnow.contracts import (
    ConfigPatch,
    Contract,
    EvidenceRef,
    Identifier,
    InstallPlan,
    NonEmptyText,
    OperationResult,
    OperationStatus,
    PlanStep,
    UntrimmedText,
)
from stackwinnow.state.lock import ProjectLockError, project_lock

_STATE_DIR = ".stackwinnow"
_RECEIPTS_FILE = "receipts.json"


class InstallerError(Exception):
    """Raised for state errors that require explicit recovery before retrying."""


class RunnerOutcome(Contract):
    """What a step runner returns — result and any resources it created."""

    status: OperationStatus
    message: NonEmptyText
    errors: list[NonEmptyText] = Field(default_factory=list)
    owned_paths: list[UntrimmedText] = Field(default_factory=list)
    configuration_ownership: list[ConfigPatch] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)


StepRunner = Callable[[PlanStep], RunnerOutcome]


class StepReceipt(Contract):
    """Durable record of one attempted installation step."""

    schema_version: Literal[1] = 1
    step_id: Identifier
    tool_id: Identifier
    status: OperationStatus
    message: NonEmptyText
    timestamp: NonEmptyText  # ISO 8601 UTC
    dry_run: bool = False
    errors: list[NonEmptyText] = Field(default_factory=list)
    owned_paths: list[UntrimmedText] = Field(default_factory=list)
    configuration_intents: list[ConfigPatch] = Field(default_factory=list)
    configuration_ownership: list[ConfigPatch] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class ExecutionRecord(Contract):
    """All step receipts for one project root."""

    schema_version: Literal[1] = 1
    project_root: UntrimmedText
    steps: list[StepReceipt] = Field(default_factory=list)

    def receipt_for(self, step_id: str) -> StepReceipt | None:
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None

    def is_succeeded(self, step_id: str, tool_id: str) -> bool:
        """True only when a real (non-dry) run recorded success for this exact step and tool."""
        receipt = self.receipt_for(step_id)
        return (
            receipt is not None
            and receipt.status == OperationStatus.SUCCEEDED
            and receipt.tool_id == tool_id
            and not receipt.dry_run
        )


def _receipts_path(project_root: str) -> Path:
    return Path(project_root) / _STATE_DIR / _RECEIPTS_FILE


def _assert_safe_path(path: Path) -> None:
    """Raise InstallerError if the receipt file or its parent directory is a symlink."""
    if path.parent.is_symlink():
        raise InstallerError(
            f"State directory '{path.parent}' is a symlink; refusing to use it. "
            "Remove the symlink and retry."
        )
    if path.is_symlink():
        raise InstallerError(
            f"Receipt file '{path}' is a symlink; refusing to read or write state there. "
            "Remove the symlink and retry."
        )


def load_record(project_root: str) -> ExecutionRecord:
    """Load saved receipts.

    Returns an empty record when the file is absent. Raises InstallerError when
    the file exists but is corrupt, unparseable, or belongs to a different project.
    The corrupt file is left on disk for the caller to inspect and recover.
    """
    path = _receipts_path(project_root)
    _assert_safe_path(path)
    if not path.exists():
        return ExecutionRecord(project_root=project_root)
    try:
        record = ExecutionRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise InstallerError(
            f"Receipts at '{path}' are corrupt or unreadable: {exc}. "
            "Inspect the file, resolve the issue, then retry."
        ) from exc
    if record.project_root != project_root:
        raise InstallerError(
            f"Receipt project root '{record.project_root}' does not match "
            f"the requested project '{project_root}'. "
            "The file may have been copied from another project."
        )
    return record


def _persist(record: ExecutionRecord, *, project_root: str) -> None:
    """Atomically write receipts to disk.

    Writes to a staging file in the same directory, then renames to the final
    path so the existing file is never truncated before the new data is complete.
    """
    path = _receipts_path(project_root)
    _assert_safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".receipts-", suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(record.model_dump_json(indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        _assert_safe_path(path)
        tmp.replace(path)  # atomic on POSIX (same filesystem)
    finally:
        tmp.unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _config_still_matches(patch: ConfigPatch, project_root: str) -> bool:
    file_path = Path(project_root) / patch.relative_path
    if patch.written_file.exists:
        if not file_path.is_file():
            return False
        if patch.written_file.sha256 is not None:
            try:
                return (
                    hashlib.sha256(file_path.read_bytes()).hexdigest() == patch.written_file.sha256
                )
            except OSError:
                return False
        return True
    return not file_path.exists()


def _record_step(record: ExecutionRecord, receipt: StepReceipt) -> None:
    """Replace any previous receipt for this step, then append the new one."""
    record.steps = [s for s in record.steps if s.step_id != receipt.step_id]
    record.steps.append(receipt)


def execute_plan(
    plan: InstallPlan,
    *,
    dry_run: bool = False,
    step_runner: StepRunner | None = None,
    configuration_intents: Mapping[str, list[ConfigPatch]] | None = None,
) -> tuple[ExecutionRecord, list[OperationResult]]:
    """Execute each step in order, persisting a receipt after every real step.

    - dry_run=True: no step_runner is called and nothing is written to disk.
    - step_runner=None and not dry_run: steps are recorded as BLOCKED.
    - Already-succeeded steps (same step_id AND tool_id from a prior real run) are skipped.
    - Execution stops after the first FAILED or BLOCKED step; remaining steps are
      reported as SKIPPED so their side effects are never triggered.
    - An intent receipt (status=FAILED) is written before the runner is invoked so
      that an interrupted run leaves an explicit record rather than silent corruption.
    - Raises InstallerError if receipts are corrupt or belong to another project;
      the caller must resolve the state before retrying.
    """
    intents: dict[str, list[ConfigPatch]] = {}
    steps = {step.step_id: step for step in plan.steps}
    for step_id, patches in (configuration_intents or {}).items():
        if step_id not in steps:
            raise InstallerError("Configuration intent refers to an unknown plan step.")
        intents[step_id] = []
        for patch in patches:
            # Frozen contracts can contain mutable JSON or unchecked model_copy updates.
            # Revalidate a detached Python snapshot without a JSON encoding round trip.
            checked = ConfigPatch.model_validate(patch.model_dump(warnings=False))
            if (
                checked.project_root != plan.project_root
                or checked.tool_id != steps[step_id].tool_id
            ):
                raise InstallerError("Configuration intent does not match the step's project/tool.")
            intents[step_id].append(checked)
    if dry_run:
        # Dry runs never touch disk, so there is nothing to serialise; skip the
        # lock to avoid creating an empty .stackwinnow/ directory as a side-effect.
        return _run_locked(plan, intents, dry_run=True, step_runner=step_runner)
    try:
        with project_lock(plan.project_root):
            return _run_locked(plan, intents, dry_run=False, step_runner=step_runner)
    except ProjectLockError as exc:
        # Re-raise as InstallerError so callers only need to handle one error type
        # from this function; ProjectLockError remains the public type for direct
        # project_lock() usage.
        raise InstallerError(str(exc)) from exc


def _run_locked(
    plan: InstallPlan,
    intents: dict[str, list[ConfigPatch]],
    *,
    dry_run: bool,
    step_runner: StepRunner | None,
) -> tuple[ExecutionRecord, list[OperationResult]]:
    record = load_record(plan.project_root)
    results: list[OperationResult] = []

    for index, step in enumerate(plan.steps):
        # --- stale-aware skip decision -----------------------------------
        # A succeeded receipt is only trusted when its owned paths still exist on
        # disk.  If all owned paths have disappeared the receipt is stale: surface
        # the discrepancy and re-run the step instead of silently skipping it.
        if record.is_succeeded(step.step_id, step.tool_id):
            succeeded_receipt = record.receipt_for(step.step_id)
            stale = False
            if succeeded_receipt is not None:
                # Use all() so a partial uninstall (some but not all owned paths
                # removed) is still caught — any() would silently skip the step
                # as long as one path survived.
                if succeeded_receipt.owned_paths and not all(
                    (Path(p) if Path(p).is_absolute() else Path(plan.project_root) / p).exists()
                    for p in succeeded_receipt.owned_paths
                ):
                    stale = True
                elif succeeded_receipt.configuration_ownership and not all(
                    _config_still_matches(patch, plan.project_root)
                    for patch in succeeded_receipt.configuration_ownership
                ):
                    stale = True
            if not stale:
                result = OperationResult(
                    status=OperationStatus.SKIPPED,
                    message=f"Step '{step.step_id}' already completed in a previous run.",
                    tool_id=step.tool_id,
                    step_id=step.step_id,
                )
                results.append(result)
                continue
            # Stale: fall through so the step is re-executed below.
        # -----------------------------------------------------------------

        if dry_run:
            result = OperationResult(
                status=OperationStatus.SKIPPED,
                message=f"Dry run: would execute — {step.description}",
                tool_id=step.tool_id,
                step_id=step.step_id,
            )
            results.append(result)
            continue

        previous = record.receipt_for(step.step_id)
        if previous is not None and (previous.tool_id != step.tool_id or previous.dry_run):
            previous = None
        ownership = list(previous.configuration_ownership) if previous is not None else []
        step_intents = list(previous.configuration_intents) if previous is not None else []
        step_intents.extend(
            patch for patch in intents.get(step.step_id, []) if patch not in step_intents
        )

        if step_runner is not None:
            # Persist intent before invoking the runner so crashes leave a record.
            intent = StepReceipt(
                step_id=step.step_id,
                tool_id=step.tool_id,
                status=OperationStatus.FAILED,
                message="Step execution began but did not complete.",
                timestamp=_now(),
                configuration_intents=step_intents,
                configuration_ownership=ownership,
            )
            _record_step(record, intent)
            _persist(record, project_root=plan.project_root)

            raw = step_runner(step)  # may raise; intent receipt remains on disk
            # Retain the original values through retries, including a no-op after
            # publication/cleanup failure. New writes append restoration history.
            ownership.extend(
                patch for patch in raw.configuration_ownership if patch not in ownership
            )

            result = OperationResult(
                status=raw.status,
                message=raw.message,
                tool_id=step.tool_id,
                step_id=step.step_id,
                errors=raw.errors,
                evidence=raw.evidence,
            )
            receipt = StepReceipt(
                step_id=step.step_id,
                tool_id=step.tool_id,
                status=raw.status,
                message=raw.message,
                timestamp=_now(),
                errors=raw.errors,
                owned_paths=raw.owned_paths,
                configuration_intents=step_intents,
                configuration_ownership=ownership,
                evidence=raw.evidence,
            )
        else:
            result = OperationResult(
                status=OperationStatus.BLOCKED,
                message=f"No runner registered for step '{step.step_id}'.",
                tool_id=step.tool_id,
                step_id=step.step_id,
                errors=["Register a step runner before executing plans."],
            )
            receipt = StepReceipt(
                step_id=step.step_id,
                tool_id=step.tool_id,
                status=OperationStatus.BLOCKED,
                message=result.message,
                timestamp=_now(),
                errors=result.errors,
                configuration_intents=step_intents,
                configuration_ownership=ownership,
            )

        _record_step(record, receipt)
        _persist(record, project_root=plan.project_root)
        results.append(result)

        # Stop after failure so dependent steps are never triggered.
        if result.status in (OperationStatus.FAILED, OperationStatus.BLOCKED):
            for remaining in plan.steps[index + 1 :]:
                results.append(
                    OperationResult(
                        status=OperationStatus.SKIPPED,
                        message=f"Step '{remaining.step_id}' not executed — a preceding step failed.",
                        tool_id=remaining.tool_id,
                        step_id=remaining.step_id,
                    )
                )
            break

    return record, results

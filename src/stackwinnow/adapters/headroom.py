"""Pinned headroom-ai library integration for context compression.

Uses the library mode only: a managed Python virtualenv is created under the
project-local .stackwinnow prefix and compression is exercised in an isolated
subprocess against a fixed fixture input.  No API keys are required; the
headroom-ai compress() function runs locally using NLP algorithms.

The proxy and client-wrapper modes are not implemented here — they require a
running assistant process and routing evidence that cannot be validated without
an active session.  Library mode is the most directly verifiable choice for a
pinned integration check.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import Field, StrictBool, StrictInt, model_validator

from stackwinnow.adapters import headroom_state as state
from stackwinnow.adapters._managed import directories, record_for
from stackwinnow.adapters.graphify_index import _publish
from stackwinnow.adapters.graphify_plan import _digest, _json
from stackwinnow.catalog import CatalogError, load_catalog
from stackwinnow.contracts import (
    Contract,
    EvidenceRef,
    InstallPlan,
    OperationResult,
    OperationStatus,
    PlanStep,
    UntrimmedText,
)
from stackwinnow.environments import (
    EnvironmentBoundaryError,
    bootstrap_pip_args,
    create_venv_args,
    pip_install_args,
    python_env_path,
    python_executable,
)
from stackwinnow.installer import (
    ExecutionRecord,
    InstallerError,
    RunnerOutcome,
    execute_plan,
)

VERSION = "0.44.0"
_TOOL_ID = "headroom"
_PACKAGE_NAME = "headroom-ai"
_DIST_INFO_NAME = "headroom_ai"  # pip normalises hyphens to underscores

# Fixed fixture for deterministic verification.  Repetitive content that the
# compression algorithm can process without network calls.
_FIXTURE_MESSAGES: list[dict] = [
    {"role": "system", "content": "You are a helpful assistant."},
    {
        "role": "user",
        "content": (
            "Review this test output:\n"
            + "PASS test_query ... ok\n" * 20
            + "PASS test_connect ... ok\n" * 20
            + "FAIL test_timeout: AssertionError: expected 0.5s got 10.2s\n"
        ),
    },
]
_FIXTURE_INPUT = json.dumps(_FIXTURE_MESSAGES, separators=(",", ":"), ensure_ascii=False)
_FIXTURE_SHA256 = hashlib.sha256(_FIXTURE_INPUT.encode()).hexdigest()

# Tokenizer target.  headroom uses tiktoken to count tokens; no model API
# calls are made during compression.  "gpt-4o" selects o200k_base.
_MODEL_TARGET = "gpt-4o"


class HeadroomError(ValueError):
    """An invalid request or a project state requiring explicit recovery."""


class CommandOutcome(Protocol):
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool

    @property
    def succeeded(self) -> bool: ...


class CommandRunner(Protocol):
    def __call__(
        self,
        args: list[str],
        *,
        cwd: str | Path,
        timeout: int,
        extra_env: dict[str, str] | None = None,
    ) -> CommandOutcome: ...


class HeadroomPlan(Contract):
    """Fully-specified plan for one headroom library installation and check."""

    schema_version: Literal[1] = 1
    tool_id: Literal["headroom"] = "headroom"
    version: Literal["0.44.0"] = VERSION
    mode: Literal["library"] = "library"
    model_target: str = _MODEL_TARGET
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    fixture_sha256: str = Field(default=_FIXTURE_SHA256, pattern=r"^[a-f0-9]{64}$")
    project_root: UntrimmedText
    installation: InstallPlan


class CompressionEvidence(Contract):
    """Recorded output from a fixture compression run."""

    messages_in: StrictInt = Field(ge=1)
    messages_out: StrictInt = Field(ge=1)
    tokens_before: StrictInt = Field(ge=1)
    tokens_after: StrictInt = Field(ge=1)
    tokens_saved: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def consistent_counts(self):
        if self.tokens_before - self.tokens_after != self.tokens_saved:
            raise ValueError("Token counts and savings disagree.")
        return self


class CompressionRun(CompressionEvidence):
    run_id: str
    fixture_sha256: Literal[_FIXTURE_SHA256]
    model_target: Literal["gpt-4o"]
    tokenizer: Literal["o200k_base"]
    system_preserved: StrictBool
    failure_preserved: StrictBool

    @model_validator(mode="after")
    def preserved_fixture(self):
        if self.messages_in != len(_FIXTURE_MESSAGES):
            raise ValueError("Fixture input count mismatch.")
        if not self.system_preserved or not self.failure_preserved:
            raise ValueError("Required fixture content did not survive.")
        return self


class HeadroomResult(Contract):
    schema_version: Literal[1] = 1
    plan: HeadroomPlan
    status: OperationStatus
    message: str
    dry_run: bool = False
    results: list[OperationResult] = Field(default_factory=list)
    record: ExecutionRecord | None = None
    compression: CompressionEvidence | None = None


def _reject_link(path: Path, label: str = "managed path") -> None:
    """Raise HeadroomError if path is a symbolic link."""
    if path.is_symlink():
        raise HeadroomError(
            f"The {label} '{path}' is a symbolic link; "
            "refusing to install outside the project boundary. "
            "Remove the symlink before retrying."
        )


def _isolated_args(args: list[str]) -> list[str]:
    """Insert -I after the Python executable in a python -m ... command."""
    if len(args) >= 2 and args[1] == "-m":
        return [args[0], "-I", "-m"] + args[2:]
    return list(args)


def _check_catalog_eligibility() -> None:
    """Raise HeadroomError if the catalog is unavailable or the license is not reviewed."""
    try:
        entry = load_catalog().get("headroom")
    except KeyError as exc:
        raise HeadroomError("headroom is not in the tool catalog.") from exc
    except CatalogError as exc:
        raise HeadroomError("The tool catalog is unavailable or invalid.") from exc
    if entry.license != "Apache-2.0" or entry.license_review != "reviewed":
        raise HeadroomError("The headroom OSS license review is not available.")


def _root(value: str | Path) -> Path:
    try:
        path = Path(value).resolve(strict=True)
        if not path.is_dir():
            raise HeadroomError("Select an existing project directory.")
        return path
    except (OSError, RuntimeError, ValueError) as exc:
        raise HeadroomError("Select an existing project directory.") from exc


def _compress_script(run_id: str = "standalone") -> str:
    """Run the reviewed local-only fixture and expose upstream token measurements."""
    return f"""# stackwinnow-headroom-compress
import json, sys
SW_RUN_ID = {run_id!r}
try:
    from headroom import compress
    from tiktoken.model import encoding_name_for_model
    messages = json.loads({_FIXTURE_INPUT!r})
    result = compress(messages, model={_MODEL_TARGET!r}, kompress_model="disabled")
    system_ok = any(m.get("role") == "system" and m.get("content") == "You are a helpful assistant."
                    for m in result.messages if isinstance(m, dict))
    failure_ok = any("FAIL test_timeout: AssertionError: expected 0.5s got 10.2s" in str(m.get("content", ""))
                     for m in result.messages if isinstance(m, dict))
    print(json.dumps({{"run_id": SW_RUN_ID, "fixture_sha256": {_FIXTURE_SHA256!r},
        "model_target": {_MODEL_TARGET!r}, "tokenizer": encoding_name_for_model({_MODEL_TARGET!r}),
        "messages_in": len(messages), "messages_out": len(result.messages),
        "tokens_before": result.tokens_before, "tokens_after": result.tokens_after,
        "tokens_saved": result.tokens_saved, "system_preserved": system_ok,
        "failure_preserved": failure_ok}}))
except Exception:
    print("Headroom fixture execution failed.", file=sys.stderr)
    sys.exit(1)
"""


def _record(root: Path) -> ExecutionRecord:
    try:
        return record_for(root)
    except (OSError, ValueError, RuntimeError) as exc:
        raise HeadroomError("Existing receipts need inspection before execution.") from exc


def _check_installation(root: Path, record: ExecutionRecord | None = None) -> bool:
    try:
        # Preserve explicit path diagnostics before using the bounded inventory.
        venv = python_env_path(str(root), _TOOL_ID)
        _reject_link(venv.parent, "tool directory")
        _reject_link(venv, "managed venv")
        return state.inspect_installation(root) is not None
    except (OSError, ValueError, RuntimeError, EnvironmentBoundaryError) as exc:
        raise HeadroomError(str(exc)) from exc


def _installation(root: Path, run_id: str) -> InstallPlan:
    return InstallPlan(
        project_root=str(root),
        tool_ids=[_TOOL_ID],
        steps=[
            PlanStep(
                step_id=f"headroom-{run_id}-install",
                tool_id=_TOOL_ID,
                description=f"Create Python venv and install {_PACKAGE_NAME}@{VERSION}.",
            ),
            PlanStep(
                step_id=f"headroom-{run_id}-compress",
                tool_id=_TOOL_ID,
                description="Run fixture compression to verify library mode.",
            ),
        ],
    )


def _build_plan(root: Path, *, run_id: str) -> HeadroomPlan:
    return HeadroomPlan(
        run_id=run_id,
        project_root=str(root),
        fixture_sha256=_FIXTURE_SHA256,
        installation=_installation(root, run_id),
    )


def _validate_plan(root: Path, plan: HeadroomPlan) -> None:
    _check_catalog_eligibility()
    if str(_root(root)) != plan.project_root:
        raise HeadroomError("The project path now resolves elsewhere; create a new plan.")
    record = _record(root)
    if any(record.receipt_for(step.step_id) is not None for step in plan.installation.steps):
        raise HeadroomError("This plan was already attempted. Create a new plan for a fresh run.")
    if _build_plan(root, run_id=plan.run_id) != plan:
        raise HeadroomError("The reviewed plan or fixed fixture changed; create a new plan.")
    _check_installation(root)


def _default_runner() -> CommandRunner | None:
    from stackwinnow.runner import run_command

    return run_command


def plan_headroom(project_root: str | Path) -> HeadroomPlan:
    """Read-only preview; no subprocesses, downloads, or writes."""
    root = _root(project_root)
    _check_catalog_eligibility()
    _check_installation(root)
    return _build_plan(root, run_id=uuid4().hex)


def _install_step(root: Path, step: PlanStep, runner: CommandRunner) -> RunnerOutcome:
    owned: list[str] = []
    label = "installation validation"
    try:
        existing = state.inspect_installation(root)
        if existing is not None:
            return RunnerOutcome(
                status=OperationStatus.SUCCEEDED,
                message=f"headroom-ai {VERSION} reused (current inventory verified).",
                owned_paths=state.owned_paths(root),
                evidence=[EvidenceRef(source=state.MANIFEST, detail="sha256:" + existing[1])],
            )
        venv = root / state.ENV
        directories(root, ".stackwinnow/envs/headroom", create=True)
        venv.mkdir(mode=0o700)
        owned.append(str(venv))
        state.journal_paths(root, step.step_id, owned)
        (root / state.STATE).mkdir(mode=0o700)
        owned.append(state.STATE)
        state.journal_paths(root, step.step_id, owned)
        state.prepare_private_paths(root)
        creation = create_venv_args(venv)
        creation.insert(-1, "--copies")
        for args, timeout, label in (
            (_isolated_args(creation), 60, "venv creation"),
            (_isolated_args(bootstrap_pip_args(venv)), 60, "pip bootstrap"),
            (
                _isolated_args(pip_install_args(venv, _PACKAGE_NAME, VERSION)),
                600,
                "headroom-ai installation",
            ),
        ):
            outcome = runner(args, cwd=root, timeout=timeout, extra_env=state.environment(root))
            if not outcome.succeeded:
                return RunnerOutcome(
                    status=OperationStatus.FAILED,
                    message=label + (" timed out." if outcome.timed_out else " failed."),
                    owned_paths=owned,
                )
        label = "installation health check"
        outcome = runner(
            [str(python_executable(venv)), "-I", "-B", "-c", state.health_script()],
            cwd=root,
            timeout=60,
            extra_env=state.environment(root),
        )
        if not outcome.succeeded or len(outcome.stdout.encode()) > 256 * 1024:
            raise HeadroomError("Headroom health check failed.")
        health = _json(outcome.stdout.encode())
        digest = state.write_manifest(root, health)
        return RunnerOutcome(
            status=OperationStatus.SUCCEEDED,
            message=f"headroom-ai {VERSION} installed; environment/imports/inventory verified.",
            owned_paths=owned,
            evidence=[EvidenceRef(source=state.MANIFEST, detail="sha256:" + digest)],
        )
    except (OSError, ValueError, RuntimeError, InstallerError, EnvironmentBoundaryError):
        return RunnerOutcome(
            status=OperationStatus.FAILED,
            message=f"Headroom {label} failed; inspect retained ownership before retrying.",
            owned_paths=owned,
        )


def run_headroom_compression(
    root: Path, step_id: str, runner: CommandRunner, *, scenario: str = "pass"
) -> tuple[RunnerOutcome, CompressionEvidence | None]:
    """Run under the shared executor lock; persist a fresh measured report."""
    measurement = None
    message = "Headroom compression failed; no fresh successful result was established."
    status = OperationStatus.FAILED
    report = {
        "schema_version": 1,
        "run_id": step_id,
        "fixture_sha256": _FIXTURE_SHA256,
        "model_target": _MODEL_TARGET,
        "tokenizer": "o200k_base",
        "scenario": scenario,
    }
    try:
        before = state.inspect_installation(root)
        if before is None:
            raise HeadroomError("Headroom is not installed.")
        state.prepare_private_paths(root)
        outcome = runner(
            [str(root / state.ENV / "bin/python"), "-I", "-B", "-c", _compress_script(step_id)],
            cwd=root,
            timeout=90,
            extra_env=state.environment(root),
        )
        if not outcome.succeeded:
            message = (
                "Compression script timed out."
                if outcome.timed_out
                else "Compression script failed."
            )
            raise HeadroomError(message)
        if len(outcome.stdout.encode()) > 64 * 1024:
            raise HeadroomError("Compression output exceeds its bound.")
        try:
            parsed = CompressionRun.model_validate(_json(outcome.stdout.encode()))
        except ValueError as exc:
            message = "Could not parse compression output; invalid counts, fixture mismatch or missing evidence."
            raise HeadroomError(message) from exc
        if parsed.run_id != step_id:
            raise HeadroomError("Compression output belongs to an earlier run.")
        after = state.inspect_installation(root)
        if after is None or before[1] != after[1]:
            raise HeadroomError("Headroom runtime changed during compression.")
        if scenario == "fail":
            message = "Negative control rejected the fresh compression result as requested."
            raise HeadroomError(message)
        measurement = CompressionEvidence.model_validate(
            {key: getattr(parsed, key) for key in CompressionEvidence.model_fields}
        )
        report["measurement"] = parsed.model_dump(mode="json")
        report["installation_sha256"] = after[1]
        status = OperationStatus.SUCCEEDED
        message = (
            f"Fixture compression succeeded ({measurement.tokens_before} tokens before, "
            f"{measurement.tokens_after} after, {measurement.tokens_saved} saved)."
        )
    except (OSError, ValueError, RuntimeError, InstallerError, EnvironmentBoundaryError):
        measurement = None
    report.update(status=status.value, message=message)
    relative = state.REPORTS + "/" + step_id + ".json"
    try:
        directories(root, state.REPORTS, create=True)
        if os.path.lexists(root / relative):
            raise HeadroomError("Refusing to replace an existing compression report.")
        raw = json.dumps(report, indent=2).encode()
        _publish(root, relative, raw)
        return RunnerOutcome(
            status=status,
            message=message,
            owned_paths=[relative],
            evidence=[EvidenceRef(source=relative, detail="sha256:" + _digest(raw))],
        ), measurement
    except (OSError, ValueError, RuntimeError):
        return RunnerOutcome(
            status=OperationStatus.FAILED,
            message="Cannot persist the fresh compression report; inspect recorded intent.",
        ), None


def apply_headroom(
    plan: HeadroomPlan, *, dry_run: bool = False, command_runner: CommandRunner | None = None
) -> HeadroomResult:
    """Apply a reviewed plan using the shared project lock and durable receipts."""
    checked = HeadroomPlan.model_validate(plan.model_dump())
    try:
        root = _root(checked.project_root)
        _validate_plan(root, checked)
        runner = command_runner or _default_runner()
        if not dry_run and runner is None:
            raise HeadroomError(
                "Headroom requires the shared command runner, which is unavailable."
            )
        if not dry_run and (platform.system() != "Darwin" or platform.machine() != "arm64"):
            raise HeadroomError("Headroom library mode currently requires macOS arm64.")
        compression = None

        def run_step(step):
            nonlocal compression
            if step.step_id.endswith("-install"):
                return _install_step(root, step, runner)
            result, compression = run_headroom_compression(root, step.step_id, runner)
            return result

        record, results = execute_plan(
            checked.installation,
            dry_run=dry_run,
            step_runner=run_step,
            before_execute=lambda: _validate_plan(root, checked),
        )
        failures = [
            r for r in results if r.status in (OperationStatus.FAILED, OperationStatus.BLOCKED)
        ]
        if dry_run:
            status, message = OperationStatus.SKIPPED, "Dry run; no commands or files were created."
        elif failures:
            status, message = failures[0].status, failures[0].message
        elif compression is None:
            status, message = OperationStatus.BLOCKED, "No fresh compression result was recorded."
        else:
            status, message = (
                OperationStatus.SUCCEEDED,
                "Headroom library-mode fixture compression passed.",
            )
        return HeadroomResult(
            plan=checked,
            status=status,
            message=message,
            dry_run=dry_run,
            results=results,
            record=record,
            compression=compression,
        )
    except (HeadroomError, InstallerError, OSError, EnvironmentBoundaryError) as exc:
        return HeadroomResult(
            plan=checked, status=OperationStatus.BLOCKED, message=str(exc), dry_run=dry_run
        )

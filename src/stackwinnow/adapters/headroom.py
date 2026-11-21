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
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import Field

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
    load_record,
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
# calls are made during compression.  "gpt-4o" selects the cl100k tokenizer.
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

    messages_in: int = Field(ge=1)
    messages_out: int = Field(ge=0)
    tokens_saved: int | None = None


class HeadroomResult(Contract):
    schema_version: Literal[1] = 1
    plan: HeadroomPlan
    status: OperationStatus
    message: str
    dry_run: bool = False
    results: list[OperationResult] = Field(default_factory=list)
    record: ExecutionRecord | None = None
    compression: CompressionEvidence | None = None


def _root(value: str | Path) -> Path:
    try:
        path = Path(value).resolve(strict=True)
        if not path.is_dir():
            raise HeadroomError("Select an existing project directory.")
        return path
    except (OSError, RuntimeError, ValueError) as exc:
        raise HeadroomError("Select an existing project directory.") from exc


def _installed_release(venv_path: Path) -> bool:
    """True if headroom-ai==VERSION is installed in the given venv."""
    try:
        lib = venv_path / "lib"
        for python_dir in lib.iterdir():
            if not python_dir.name.startswith("python"):
                continue
            dist_info = python_dir / "site-packages" / f"{_DIST_INFO_NAME}-{VERSION}.dist-info"
            if not dist_info.is_dir():
                continue
            metadata = dist_info / "METADATA"
            if not metadata.is_file():
                continue
            content = metadata.read_text(errors="replace")
            return f"Version: {VERSION}" in content and "Name: headroom-ai" in content
        return False
    except OSError:
        return False


def _compress_script() -> str:
    """Return a self-contained Python script that compresses the fixture and prints JSON."""
    fixture_repr = repr(_FIXTURE_INPUT)
    model_repr = repr(_MODEL_TARGET)
    return "\n".join(
        [
            "import json, sys",
            "try:",
            "    from headroom import compress",
            "except ImportError as e:",
            '    print(json.dumps({"error": repr(e)}), file=sys.stderr)',
            "    sys.exit(1)",
            "try:",
            f"    messages = json.loads({fixture_repr})",
            f"    result = compress(messages, model={model_repr})",
            '    out = {"messages_in": len(messages), "messages_out": len(result.messages)}',
            "    if hasattr(result, 'tokens_saved'):",
            '        out["tokens_saved"] = result.tokens_saved',
            "    print(json.dumps(out))",
            "    sys.exit(0)",
            "except Exception as e:",
            '    print(json.dumps({"error": repr(e)}), file=sys.stderr)',
            "    sys.exit(1)",
        ]
    )


def _has_path_ownership(record: ExecutionRecord, path: Path) -> bool:
    return any(
        receipt.tool_id == _TOOL_ID and str(path) in receipt.owned_paths for receipt in record.steps
    )


def _check_installation(root: Path, record: ExecutionRecord) -> bool:
    """Return True if the managed venv exists and is owned.  Raise on conflict."""
    try:
        venv = python_env_path(str(root), _TOOL_ID)
    except EnvironmentBoundaryError as exc:
        raise HeadroomError(str(exc)) from exc
    if not venv.exists():
        return False
    if not _has_path_ownership(record, venv):
        raise HeadroomError(
            "The managed headroom venv exists without an ownership receipt; "
            "inspect it before retrying."
        )
    if not _installed_release(venv):
        raise HeadroomError(
            "The owned headroom venv is incomplete or changed; inspect it before retrying."
        )
    return True


def _record(root: Path) -> ExecutionRecord:
    try:
        return load_record(str(root))
    except InstallerError as exc:
        raise HeadroomError(
            "Existing receipts need recovery; inspect .stackwinnow/receipts.json."
        ) from exc


def _installation(root: Path, run_id: str) -> InstallPlan:
    actions = [
        ("install", f"Create Python venv and install {_PACKAGE_NAME}@{VERSION}."),
        ("compress", "Run fixture compression to verify library mode."),
    ]
    return InstallPlan(
        project_root=str(root),
        tool_ids=[_TOOL_ID],
        steps=[
            PlanStep(
                step_id=f"{_TOOL_ID}-{run_id}-{action}",
                tool_id=_TOOL_ID,
                description=description,
            )
            for action, description in actions
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
    if str(_root(root)) != plan.project_root:
        raise HeadroomError("The project path now resolves elsewhere; create a new plan.")
    record = _record(root)
    if any(record.receipt_for(step.step_id) is not None for step in plan.installation.steps):
        raise HeadroomError("This plan was already attempted. Create a new plan for a fresh run.")
    if plan.fixture_sha256 != _FIXTURE_SHA256:
        raise HeadroomError("The fixture changed; recreate the plan.")
    expected = _build_plan(root, run_id=plan.run_id)
    if expected != plan:
        raise HeadroomError(
            "The plan or its input configuration changed; create and review a new plan."
        )


@contextmanager
def _operation_lock(root: Path) -> Iterator[None]:
    managed = root / ".stackwinnow"
    managed.mkdir(mode=0o700, exist_ok=True)
    lock_path = managed / "headroom.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    except FileExistsError as exc:
        raise HeadroomError(
            "Another headroom operation may be active. Inspect the lock before retrying."
        ) from exc
    try:
        os.close(descriptor)
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def _default_runner() -> CommandRunner | None:
    try:
        from stackwinnow.runner import run_command
    except ModuleNotFoundError as exc:
        if exc.name != "stackwinnow.runner":
            raise
        return None
    return run_command


def plan_headroom(project_root: str | Path) -> HeadroomPlan:
    """Preview the headroom library installation without commands, network, or writes."""
    root = _root(project_root)
    try:
        entry = load_catalog().get("headroom")
    except KeyError as exc:
        raise HeadroomError("headroom is not in the tool catalog.") from exc
    except CatalogError as exc:
        raise HeadroomError("The tool catalog is unavailable or invalid.") from exc
    if entry.license != "Apache-2.0" or entry.license_review != "reviewed":
        raise HeadroomError("The headroom OSS license review is not available.")
    record = _record(root)
    _check_installation(root, record)
    return _build_plan(root, run_id=uuid4().hex)


def apply_headroom(
    plan: HeadroomPlan,
    *,
    dry_run: bool = False,
    command_runner: CommandRunner | None = None,
) -> HeadroomResult:
    """Apply a reviewed headroom plan.

    Installs headroom-ai in an isolated venv and verifies library-mode
    compression against a fixed fixture.  Dry-run leaves the filesystem
    unchanged; a real run requires the shared command runner.
    """
    checked = HeadroomPlan.model_validate_json(plan.model_dump_json())

    def blocked(message: str) -> HeadroomResult:
        return HeadroomResult(
            plan=checked,
            status=OperationStatus.BLOCKED,
            message=message,
            dry_run=dry_run,
        )

    try:
        root = _root(checked.project_root)
        _validate_plan(root, checked)
        if dry_run:
            record, results = execute_plan(checked.installation, dry_run=True)
            return HeadroomResult(
                plan=checked,
                status=OperationStatus.SKIPPED,
                message="Dry run; no commands or files were created.",
                dry_run=True,
                record=record,
                results=results,
            )
        runner = command_runner or _default_runner()
        if runner is None:
            return blocked(
                "headroom execution requires the shared command runner, which is unavailable "
                "in this build. Use a dry run or a build that includes the runner."
            )
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            return blocked(
                "The initial headroom adapter is validated on macOS arm64; "
                "other environments remain unverified."
            )

        compression: CompressionEvidence | None = None

        def run_step(step: PlanStep) -> RunnerOutcome:
            nonlocal compression
            venv = python_env_path(str(root), _TOOL_ID)
            owned_paths = [str(venv)]

            if step.step_id.endswith("-install"):
                already_installed = _check_installation(root, load_record(str(root)))
                if not already_installed:
                    if venv.exists():
                        return RunnerOutcome(
                            status=OperationStatus.BLOCKED,
                            message=(
                                "The venv appeared or changed between plan and apply; "
                                "inspect it before retrying."
                            ),
                        )
                    # Create venv without pip, then bootstrap pip, then install.
                    for args, timeout, label in [
                        (create_venv_args(venv), 60, "venv creation"),
                        (bootstrap_pip_args(venv), 60, "pip bootstrap"),
                        (
                            pip_install_args(venv, _PACKAGE_NAME, VERSION),
                            600,
                            f"{_PACKAGE_NAME} installation",
                        ),
                    ]:
                        outcome = runner(args, cwd=root, timeout=timeout)
                        if not outcome.succeeded:
                            return RunnerOutcome(
                                status=(
                                    OperationStatus.BLOCKED
                                    if outcome.timed_out
                                    else OperationStatus.FAILED
                                ),
                                message=(
                                    f"{label} timed out."
                                    if outcome.timed_out
                                    else f"{label} failed: {outcome.stderr[:200]}"
                                ),
                                owned_paths=owned_paths,
                            )
                if not _installed_release(venv):
                    return RunnerOutcome(
                        status=OperationStatus.FAILED,
                        message=(
                            f"The installed package does not match {_PACKAGE_NAME}=={VERSION}."
                        ),
                        owned_paths=owned_paths,
                    )
                return RunnerOutcome(
                    status=OperationStatus.SUCCEEDED,
                    message=(
                        f"{_PACKAGE_NAME} {VERSION} "
                        + ("reused (already installed)." if already_installed else "installed.")
                    ),
                    owned_paths=owned_paths,
                )

            # compress step: run the fixture through headroom.compress in the venv.
            tiktoken_cache = venv / "tiktoken-cache"
            tiktoken_cache.mkdir(mode=0o700, exist_ok=True)
            script = _compress_script()
            outcome = runner(
                [str(python_executable(venv)), "-I", "-c", script],
                cwd=root,
                timeout=60,
                extra_env={"TIKTOKEN_CACHE_DIR": str(tiktoken_cache)},
            )
            if not outcome.succeeded:
                raw_err = outcome.stderr.strip()[:300]
                return RunnerOutcome(
                    status=OperationStatus.FAILED,
                    message=(
                        "Compression script timed out."
                        if outcome.timed_out
                        else f"Compression script failed: {raw_err}"
                    ),
                )
            try:
                data = json.loads(outcome.stdout.strip())
                if "error" in data:
                    return RunnerOutcome(
                        status=OperationStatus.FAILED,
                        message=f"headroom.compress raised an exception: {data['error'][:200]}",
                    )
                compression = CompressionEvidence(
                    messages_in=data["messages_in"],
                    messages_out=data["messages_out"],
                    tokens_saved=data.get("tokens_saved"),
                )
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                return RunnerOutcome(
                    status=OperationStatus.FAILED,
                    message=f"Could not parse compression output: {exc}",
                )
            detail = f"{compression.messages_in} messages in, {compression.messages_out} out" + (
                f", {compression.tokens_saved} tokens saved"
                if compression.tokens_saved is not None
                else ""
            )
            return RunnerOutcome(
                status=OperationStatus.SUCCEEDED,
                message=f"Fixture compression succeeded ({detail}).",
                evidence=[EvidenceRef(source="headroom.compress", detail=detail)],
            )

        with _operation_lock(root):
            _validate_plan(root, checked)
            record, results = execute_plan(checked.installation, step_runner=run_step)

        failures = [
            r for r in results if r.status in (OperationStatus.FAILED, OperationStatus.BLOCKED)
        ]
        if failures:
            status, message = failures[0].status, failures[0].message
        elif compression is None or not any(
            r.step_id == checked.installation.steps[-1].step_id
            and r.status == OperationStatus.SUCCEEDED
            for r in results
        ):
            status = OperationStatus.BLOCKED
            message = "No fresh successful compression was recorded. Create a new plan."
        else:
            status = OperationStatus.SUCCEEDED
            message = "headroom is installed and library-mode compression passed."
        return HeadroomResult(
            plan=checked,
            status=status,
            message=message,
            results=results,
            record=record,
            compression=compression,
        )
    except (HeadroomError, InstallerError, OSError, EnvironmentBoundaryError) as exc:
        message = (
            str(exc)
            if isinstance(exc, HeadroomError)
            else "Project state changed; inspect the managed receipts and create a new plan."
        )
        return blocked(message)

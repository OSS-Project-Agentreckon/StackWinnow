"""LlamaIndex adapter — library mode.

Installs the llama-index package in a managed venv and verifies the import works.
No API key or running backend is required; this checks library availability only.
"""

from __future__ import annotations

import platform
from collections.abc import Callable
from pathlib import Path
from typing import Literal
from uuid import uuid4

from stackwinnow.adapters._managed import ManagedStateError
from stackwinnow.adapters._py_adapter import (
    build_install_plan,
    inspect_installation,
    run_install_step,
    run_verify_step,
)
from stackwinnow.contracts import Contract, InstallPlan, OperationResult, OperationStatus, UntrimmedText
from stackwinnow.environments import EnvironmentBoundaryError
from stackwinnow.installer import ExecutionRecord, InstallerError, execute_plan

VERSION = "0.14.26"
_TOOL_ID = "llama-index"
_PACKAGE_NAME = "llama-index"
_MODULE_NAME = "llama_index"
_DIST_NAME = "llama-index"


class LlamaIndexError(ValueError):
    """An invalid request or a project state requiring explicit recovery."""


class LlamaIndexPlan(Contract):
    schema_version: Literal[1] = 1
    tool_id: Literal["llama-index"] = "llama-index"
    version: Literal["0.14.26"] = VERSION
    mode: Literal["library"] = "library"
    run_id: str
    project_root: UntrimmedText
    installation: InstallPlan


class LlamaIndexResult(Contract):
    schema_version: Literal[1] = 1
    plan: LlamaIndexPlan
    status: OperationStatus
    message: str
    dry_run: bool = False
    results: list[OperationResult] = []
    record: ExecutionRecord | None = None


def _root(value: str | Path) -> Path:
    try:
        path = Path(value).resolve(strict=True)
        if not path.is_dir():
            raise LlamaIndexError("Select an existing project directory.")
        return path
    except (OSError, RuntimeError, ValueError) as exc:
        raise LlamaIndexError("Select an existing project directory.") from exc


def plan_llama_index(project_root: str | Path) -> LlamaIndexPlan:
    root = _root(project_root)
    inspect_installation(root, _TOOL_ID, VERSION)
    run_id = uuid4().hex
    return LlamaIndexPlan(
        run_id=run_id,
        project_root=str(root),
        installation=build_install_plan(root, _TOOL_ID, _PACKAGE_NAME, VERSION, run_id),
    )


def apply_llama_index(
    plan: LlamaIndexPlan,
    *,
    dry_run: bool = False,
    command_runner=None,
    before_execute: Callable[[], None] | None = None,
) -> LlamaIndexResult:
    checked = LlamaIndexPlan.model_validate(plan.model_dump())
    try:
        root = _root(checked.project_root)
        if not dry_run and (platform.system() != "Darwin" or platform.machine() != "arm64"):
            raise LlamaIndexError("LlamaIndex library mode currently requires macOS arm64.")
        from stackwinnow.runner import run_command
        runner = command_runner or run_command
        if not dry_run and runner is None:
            raise LlamaIndexError("LlamaIndex requires the shared command runner.")

        def run_step(step):
            if step.step_id.endswith("-install"):
                return run_install_step(root, step, runner, _TOOL_ID, _PACKAGE_NAME, VERSION)
            return run_verify_step(root, step, runner, _TOOL_ID, _MODULE_NAME, _DIST_NAME, VERSION)

        from stackwinnow.adapters._composition import validate_and_guard
        record, results = execute_plan(
            checked.installation,
            dry_run=dry_run,
            step_runner=run_step,
            before_execute=lambda: validate_and_guard(lambda: None, before_execute),
        )
        failures = [r for r in results if r.status in (OperationStatus.FAILED, OperationStatus.BLOCKED)]
        if dry_run:
            status, message = OperationStatus.SKIPPED, "Dry run; no commands or files were created."
        elif failures:
            status, message = failures[0].status, failures[0].message
        else:
            status, message = OperationStatus.SUCCEEDED, f"llama-index {{VERSION}} library installation verified."
        return LlamaIndexResult(plan=checked, status=status, message=message, dry_run=dry_run, results=results, record=record)
    except (LlamaIndexError, InstallerError, OSError, EnvironmentBoundaryError, ManagedStateError) as exc:
        return LlamaIndexResult(plan=checked, status=OperationStatus.BLOCKED, message=str(exc), dry_run=dry_run)

"""Managed Graphify indexing and relationship verification (B04).

Requires a succeeded Graphify install receipt. Runs the graphify extract
command on the project source, verifies the expected relationship exists in
the resulting graph, and records owned state paths and graph evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import Field

from stackwinnow.adapters._managed import ManagedStateError, directories, record_for
from stackwinnow.adapters.graphify import (
    GRAPH_PATH,
    STATE_PATH,
    GraphifyError,
    RelationshipCheck,
    _environment,
    _root,
    check_relationship,
    index_command,
)
from stackwinnow.adapters.graphify_install import STEP_ID as INSTALL_STEP_ID
from stackwinnow.adapters.graphify_plan import ENV_PATH, GraphifyExecutionPlan, _digest, _read_at
from stackwinnow.contracts import (
    Contract,
    EvidenceRef,
    InstallPlan,
    OperationResult,
    OperationStatus,
    PlanStep,
)
from stackwinnow.installer import ExecutionRecord, InstallerError, RunnerOutcome, execute_plan
from stackwinnow.runner import CommandResult, run_command

INDEX_STEP_ID = "graphify-index-code"
CommandRunner = Callable[..., CommandResult]


class GraphifyIndexResult(Contract):
    schema_version: Literal[1] = 1
    tool_id: Literal["graphify"] = "graphify"
    scope: Literal["local-index-only"] = "local-index-only"
    dry_run: bool
    indexed: bool = False
    relationship_check: RelationshipCheck | None = None
    record: ExecutionRecord
    results: list[OperationResult] = Field(default_factory=list)


def _check_install_prereq(root: Path) -> None:
    """Raise GraphifyError unless a succeeded install receipt exists."""
    record = record_for(root)
    receipt = record.receipt_for(INSTALL_STEP_ID)
    if receipt is None or receipt.status != OperationStatus.SUCCEEDED:
        raise GraphifyError(
            "Graphify packages must be installed (apply install) before indexing."
        )


def _run_index(
    plan: GraphifyExecutionPlan,
    runner: CommandRunner,
    result_holder: list,
) -> RunnerOutcome:
    root = Path(plan.project_root)
    state = root / STATE_PATH

    # Refuse to adopt an existing, unowned state directory.
    if os.path.lexists(state):
        raise GraphifyError(
            "Graphify index state already exists; inspect it before reindexing."
        )

    # Create the state tree the index command writes into.
    directories(root, STATE_PATH, create=True)
    home = root / STATE_PATH / "home"
    home.mkdir(mode=0o700)
    (home / ".config").mkdir()
    (home / ".cache").mkdir()
    owned = [STATE_PATH]

    cmd = index_command(root, root / ENV_PATH / "bin/python")
    outcome = runner(cmd.argv, cwd=cmd.cwd, timeout=cmd.timeout_seconds, extra_env=cmd.environment)
    if not outcome.succeeded:
        return RunnerOutcome(
            status=OperationStatus.FAILED,
            message="Graphify indexing failed.",
            owned_paths=owned,
        )

    try:
        raw = _read_at(root, GRAPH_PATH)
    except (OSError, GraphifyError):
        return RunnerOutcome(
            status=OperationStatus.FAILED,
            message="Index command succeeded but graph.json is missing or unreadable.",
            owned_paths=owned,
        )

    graph = json.loads(raw)
    check = check_relationship(graph, plan.expectation)
    result_holder.append(check)

    return RunnerOutcome(
        status=check.status,
        message=check.message,
        owned_paths=owned,
        evidence=[EvidenceRef(source=GRAPH_PATH, detail=f"sha256:{_digest(raw)}")],
    )


def apply_graphify_index(
    plan: GraphifyExecutionPlan,
    *,
    dry_run: bool = False,
    command_runner: CommandRunner = run_command,
) -> GraphifyIndexResult:
    """Index project source and verify the expected relationship; install must precede this."""
    try:
        plan = GraphifyExecutionPlan.model_validate(plan.model_dump())
        root = _root(plan.project_root)
        _check_install_prereq(root)

        installation = InstallPlan(
            project_root=plan.project_root,
            tool_ids=["graphify"],
            steps=[
                PlanStep(
                    step_id=INDEX_STEP_ID,
                    tool_id="graphify",
                    description="Index project source code with Graphify and verify relationship.",
                )
            ],
        )

        check_holder: list[RelationshipCheck] = []
        record, results = execute_plan(
            installation,
            dry_run=dry_run,
            step_runner=lambda step: _run_index(plan, command_runner, check_holder),
        )
        indexed = record.is_succeeded(INDEX_STEP_ID, "graphify")
        return GraphifyIndexResult(
            dry_run=dry_run,
            indexed=indexed,
            relationship_check=check_holder[0] if check_holder else None,
            record=record,
            results=results,
        )
    except GraphifyError:
        raise
    except (OSError, ValueError, RuntimeError, ManagedStateError, InstallerError) as exc:
        raise GraphifyError(f"Cannot index project with Graphify: {exc}") from exc

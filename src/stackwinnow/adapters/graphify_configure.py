"""Managed Graphify Codex MCP server configuration (B05).

Requires both a succeeded install receipt and a succeeded index receipt.
Registers the Graphify MCP server in .codex/config.toml and records
configuration_ownership on the step receipt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from stackwinnow.adapters._managed import ManagedStateError, directories, record_for
from stackwinnow.adapters.graphify import GraphifyError, _root
from stackwinnow.adapters.graphify_index import INDEX_STEP_ID
from stackwinnow.adapters.graphify_install import STEP_ID as INSTALL_STEP_ID, graphify_server_settings
from stackwinnow.adapters.graphify_plan import GraphifyExecutionPlan
from stackwinnow.configure.codex import apply_graphify_codex_server, plan_graphify_codex_server
from stackwinnow.configure.patches import ConfigurationError
from stackwinnow.contracts import (
    Contract,
    InstallPlan,
    OperationResult,
    OperationStatus,
    PlanStep,
)
from stackwinnow.installer import ExecutionRecord, InstallerError, RunnerOutcome, execute_plan

CONFIGURE_STEP_ID = "graphify-configure"


class GraphifyConfigureResult(Contract):
    schema_version: Literal[1] = 1
    tool_id: Literal["graphify"] = "graphify"
    scope: Literal["local-configure-only"] = "local-configure-only"
    dry_run: bool
    configured: bool = False
    record: ExecutionRecord
    results: list[OperationResult] = Field(default_factory=list)


def _check_prereqs(root: Path) -> None:
    """Raise GraphifyError unless both install and index receipts are succeeded."""
    record = record_for(root)
    install_receipt = record.receipt_for(INSTALL_STEP_ID)
    if install_receipt is None or install_receipt.status != OperationStatus.SUCCEEDED:
        raise GraphifyError(
            "Graphify packages must be installed (apply install) before configuring."
        )
    index_receipt = record.receipt_for(INDEX_STEP_ID)
    if index_receipt is None or index_receipt.status != OperationStatus.SUCCEEDED:
        raise GraphifyError(
            "Graphify source must be indexed (apply index) before configuring."
        )


def _configure_step(root: Path, config_patch) -> RunnerOutcome:
    parent = root / ".codex"
    created = not parent.exists()
    if created:
        # Parent does not exist — apply_graphify_codex_server will return blocked.
        # Attempt the apply anyway to get the proper blocked result.
        pass
    else:
        directories(root, ".codex", create=False)
    applied = apply_graphify_codex_server(config_patch)
    return RunnerOutcome(
        status=applied.result.status,
        message=applied.result.message,
        configuration_ownership=[applied.ownership] if applied.ownership else [],
        owned_paths=[str(parent)] if created and applied.result.status == OperationStatus.SUCCEEDED else [],
    )


def apply_graphify_configure(
    plan: GraphifyExecutionPlan,
    *,
    dry_run: bool = False,
) -> GraphifyConfigureResult:
    """Register the Graphify MCP server in .codex/config.toml; install + index must precede."""
    try:
        plan = GraphifyExecutionPlan.model_validate(plan.model_dump())
        root = _root(plan.project_root)
        _check_prereqs(root)

        settings = graphify_server_settings(root)
        config_patch = plan_graphify_codex_server(root, settings)

        installation = InstallPlan(
            project_root=plan.project_root,
            tool_ids=["graphify"],
            steps=[
                PlanStep(
                    step_id=CONFIGURE_STEP_ID,
                    tool_id="graphify",
                    description="Register the Graphify MCP server entry in .codex/config.toml.",
                )
            ],
        )

        record, results = execute_plan(
            installation,
            dry_run=dry_run,
            step_runner=lambda step: _configure_step(root, config_patch),
            configuration_intents={CONFIGURE_STEP_ID: [config_patch]},
        )

        configured = record.is_succeeded(CONFIGURE_STEP_ID, "graphify")
        return GraphifyConfigureResult(
            dry_run=dry_run,
            configured=configured,
            record=record,
            results=results,
        )
    except GraphifyError:
        raise
    except (OSError, ValueError, RuntimeError, ManagedStateError, InstallerError, ConfigurationError) as exc:
        raise GraphifyError(f"Cannot configure Graphify Codex entry: {exc}") from exc

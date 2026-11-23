"""Owned project-scoped Codex configuration for the manager Graphify bridge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from stackwinnow.adapters._managed import directories, record_for
from stackwinnow.adapters.graphify import GraphifyError, _root
from stackwinnow.adapters.graphify_index import PROVENANCE_PATH, inspect_graphify_index
from stackwinnow.adapters.graphify_install import graphify_server_settings
from stackwinnow.adapters.graphify_plan import (
    Digest,
    GraphifyExecutionPlan,
    _digest,
    _json,
    _read_at,
)
from stackwinnow.configure.codex import (
    GRAPHIFY_KEY,
    RELATIVE_PATH,
    apply_graphify_codex_server,
    plan_graphify_codex_server,
)
from stackwinnow.configure.conflicts import reconcile_config_patch
from stackwinnow.configure.patches import ConfigurationError
from stackwinnow.contracts import (
    ConfigPatch,
    Contract,
    EvidenceRef,
    InstallPlan,
    OperationResult,
    OperationStatus,
    PlanStep,
    UntrimmedText,
)
from stackwinnow.installer import ExecutionRecord, InstallerError, RunnerOutcome, execute_plan

CONFIGURE_STEP_ID = "graphify-configure"


class GraphifyConfigurePlan(Contract):
    schema_version: Literal[1] = 1
    tool_id: Literal["graphify"] = "graphify"
    project_root: UntrimmedText
    provenance_sha256: Digest
    bridge_sha256: Digest
    configuration: ConfigPatch


class GraphifyConfigureResult(Contract):
    schema_version: Literal[1] = 1
    tool_id: Literal["graphify"] = "graphify"
    scope: Literal["local-configure-only"] = "local-configure-only"
    dry_run: bool
    configured: bool = False
    record: ExecutionRecord
    results: list[OperationResult] = Field(default_factory=list)


def registration_digest(settings: dict) -> str:
    return _digest(json.dumps(settings, sort_keys=True, separators=(",", ":")).encode())


def bridge_digest() -> str:
    from stackwinnow import graphify_bridge

    source = Path(graphify_bridge.__file__)
    return _digest(_read_at(source.parent, source.name))


def owned_graphify_configuration(root: Path) -> ConfigPatch:
    """Inspect live configuration and original ownership; never adopt a matching foreign table."""
    record = record_for(root)
    receipt = record.receipt_for(CONFIGURE_STEP_ID)
    if (
        not receipt
        or not record.is_succeeded(CONFIGURE_STEP_ID, "graphify")
        or len(receipt.configuration_ownership) != 1
        or receipt.owned_paths not in ([], [str(root / ".codex")])
    ):
        raise GraphifyError("A successful owned Graphify configuration is required.")
    patch = receipt.configuration_ownership[0]
    settings = graphify_server_settings(root)
    if (
        patch.project_root != str(root)
        or patch.tool_id != "graphify"
        or patch.relative_path != RELATIVE_PATH
        or patch.format != "toml"
        or len(patch.edits) != 1
        or patch.edits[0].key_path != GRAPHIFY_KEY
        or patch.edits[0].original.exists
        or patch.edits[0].written != settings
        or receipt.configuration_intents != [patch]
        or receipt.evidence
        != [
            EvidenceRef(
                source=RELATIVE_PATH, detail="registration-sha256:" + registration_digest(settings)
            )
        ]
    ):
        raise GraphifyError("Graphify configuration ownership or bridge registration changed.")
    report = reconcile_config_patch(patch)
    if len(report.keys) != 1 or report.keys[0].kind != "clean":
        raise GraphifyError(
            "Graphify configuration was modified, removed or is unreadable; preserve it."
        )
    return patch


def plan_graphify_configure(project_root: str | Path) -> GraphifyConfigurePlan:
    """Preview against current graph/runtime evidence without writes or commands."""
    try:
        root = _root(project_root)
        inspect_graphify_index(root)
        existing = record_for(root).receipt_for(CONFIGURE_STEP_ID)
        if existing is not None:
            patch = owned_graphify_configuration(root)
        else:
            patch = plan_graphify_codex_server(root, graphify_server_settings(root))
            if not patch.edits:
                raise GraphifyError(
                    "Matching Graphify configuration is foreign; it will not be adopted."
                )
        return GraphifyConfigurePlan(
            project_root=str(root),
            provenance_sha256=_digest(_read_at(root, PROVENANCE_PATH)),
            bridge_sha256=bridge_digest(),
            configuration=patch,
        )
    except (OSError, ValueError, RuntimeError, InstallerError, ConfigurationError) as exc:
        raise GraphifyError("Cannot plan Graphify configuration: " + str(exc)) from exc


def load_graphify_configure_plan(path: str | Path) -> GraphifyConfigurePlan:
    try:
        source = Path(path).absolute()
        return GraphifyConfigurePlan.model_validate(_json(_read_at(source.parent, source.name)))
    except (OSError, ValueError, RuntimeError) as exc:
        raise GraphifyError("Invalid Graphify configuration plan.") from exc


def apply_graphify_configure(
    plan: GraphifyConfigurePlan | GraphifyExecutionPlan, *, dry_run: bool = False
) -> GraphifyConfigureResult:
    try:
        if isinstance(plan, GraphifyExecutionPlan):
            provenance, _ = inspect_graphify_index(_root(plan.project_root))
            if provenance.plan.installation_plan != GraphifyExecutionPlan.model_validate(
                plan.model_dump()
            ):
                raise GraphifyError("Execution plan differs from the installed recipe.")
            plan = plan_graphify_configure(plan.project_root)
        checked = GraphifyConfigurePlan.model_validate(plan.model_dump())
        root = _root(checked.project_root)
        prior = None

        def validate():
            nonlocal prior
            if plan_graphify_configure(root) != checked:
                raise GraphifyError(
                    "Configuration inputs changed; review a new configuration plan."
                )
            prior = record_for(root).receipt_for(CONFIGURE_STEP_ID)

        def configure(step):
            if prior is not None:
                # The shared executor's file digest can be stale after unrelated
                # TOML edits. validate() already proved our owned key is clean.
                return RunnerOutcome(
                    status=OperationStatus.SUCCEEDED,
                    message="Reused unchanged owned Graphify settings; unrelated edits preserved.",
                    owned_paths=prior.owned_paths,
                    configuration_ownership=prior.configuration_ownership,
                    evidence=prior.evidence,
                )
            parent = root / ".codex"
            created = not parent.exists()
            owned = []
            try:
                directories(root, ".codex", create=True)
                if created:
                    owned.append(str(parent))
                applied = apply_graphify_codex_server(checked.configuration)
                return RunnerOutcome(
                    status=applied.result.status,
                    message=applied.result.message,
                    owned_paths=owned,
                    configuration_ownership=[applied.ownership] if applied.ownership else [],
                    evidence=[
                        EvidenceRef(
                            source=RELATIVE_PATH,
                            detail="registration-sha256:"
                            + registration_digest(graphify_server_settings(root)),
                        )
                    ]
                    if applied.ownership
                    else [],
                )
            except (OSError, ValueError, RuntimeError, ConfigurationError):
                return RunnerOutcome(
                    status=OperationStatus.FAILED,
                    message="Graphify configuration failed; inspect the recorded intent.",
                    owned_paths=owned,
                )

        installation = InstallPlan(
            project_root=str(root),
            tool_ids=["graphify"],
            steps=[
                PlanStep(
                    step_id=CONFIGURE_STEP_ID,
                    tool_id="graphify",
                    description="Register the owned Graphify bridge in project Codex settings.",
                )
            ],
        )
        record, results = execute_plan(
            installation,
            dry_run=dry_run,
            before_execute=validate,
            step_runner=configure,
            configuration_intents={CONFIGURE_STEP_ID: [checked.configuration]},
        )
        return GraphifyConfigureResult(
            dry_run=dry_run,
            configured=record.is_succeeded(CONFIGURE_STEP_ID, "graphify"),
            record=record,
            results=results,
        )
    except GraphifyError:
        raise
    except (OSError, ValueError, RuntimeError, InstallerError, ConfigurationError) as exc:
        raise GraphifyError(
            "Cannot configure Graphify; inspect the plan and recorded ownership."
        ) from exc

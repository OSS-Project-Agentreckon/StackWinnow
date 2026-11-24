"""Explicit, reviewed orchestration of the four supported local adapter modes."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from stackwinnow.adapters import headroom, playwright_mcp, promptfoo
from stackwinnow.adapters import langfuse as langfuse_adapter
from stackwinnow.adapters import opik as opik_adapter
from stackwinnow.adapters import ragas as ragas_adapter
from stackwinnow.adapters import trulens as trulens_adapter
from stackwinnow.adapters import deepeval as deepeval_adapter
from stackwinnow.adapters import inspect_ai as inspect_ai_adapter
from stackwinnow.adapters import openlit as openlit_adapter
from stackwinnow.adapters import langchain as langchain_adapter
from stackwinnow.adapters import litellm as litellm_adapter
from stackwinnow.adapters import llmlingua as llmlingua_adapter
from stackwinnow.adapters import gptcache as gptcache_adapter
from stackwinnow.adapters import dspy as dspy_adapter
from stackwinnow.adapters import llama_index as llama_index_adapter
from stackwinnow.adapters import pydantic_ai as pydantic_ai_adapter
from stackwinnow.adapters import haystack as haystack_adapter
from stackwinnow.adapters import langgraph as langgraph_adapter
from stackwinnow.adapters import crewai as crewai_adapter
from stackwinnow.adapters import autogen as autogen_adapter
from stackwinnow.adapters import smolagents as smolagents_adapter
from stackwinnow.adapters._managed import directories, read_json, record_for
from stackwinnow.adapters.graphify import RelationshipExpectation, _root
from stackwinnow.adapters.graphify_configure import (
    CONFIGURE_STEP_ID,
    apply_graphify_configure,
    bridge_digest,
    owned_graphify_configuration,
    plan_graphify_configure,
)
from stackwinnow.adapters.graphify_index import (
    INDEX_STEP_ID,
    PROVENANCE_PATH,
    _publish,
    apply_graphify_index,
    inspect_graphify_index,
    plan_graphify_index,
)
from stackwinnow.adapters.graphify_install import (
    STEP_ID,
    apply_graphify_install,
    graphify_server_settings,
    validate_graphify_installation,
)
from stackwinnow.adapters.graphify_plan import (
    GRAPH_PATH,
    LOCK_SHA256,
    GraphifyExecutionPlan,
    _digest,
    plan_graphify_execution,
)
from stackwinnow.adapters.headroom import HeadroomPlan
from stackwinnow.adapters.playwright_mcp import PlaywrightPlan
from stackwinnow.adapters.promptfoo import PromptfooPlan
from stackwinnow.adapters.opik import OpikPlan
from stackwinnow.adapters.langfuse import LangfusePlan
from stackwinnow.adapters.ragas import RagasPlan
from stackwinnow.adapters.trulens import TrulensPlan
from stackwinnow.adapters.deepeval import DeepevalPlan
from stackwinnow.adapters.inspect_ai import InspectAiPlan
from stackwinnow.adapters.openlit import OpenlitPlan
from stackwinnow.adapters.langchain import LangchainPlan
from stackwinnow.adapters.litellm import LitellmPlan
from stackwinnow.adapters.llmlingua import LlmlinguaPlan
from stackwinnow.adapters.gptcache import GptcachePlan
from stackwinnow.adapters.dspy import DspyPlan
from stackwinnow.adapters.llama_index import LlamaIndexPlan
from stackwinnow.adapters.pydantic_ai import PydanticAiPlan
from stackwinnow.adapters.haystack import HaystackPlan
from stackwinnow.adapters.langgraph import LanggraphPlan
from stackwinnow.adapters.crewai import CrewaiPlan
from stackwinnow.adapters.autogen import AutogenPlan
from stackwinnow.adapters.smolagents import SmolagentsPlan
from stackwinnow.configure.codex import plan_graphify_codex_server
from stackwinnow.contracts import ConfigPatch, Contract, OperationStatus
from stackwinnow.detect import ModelPreference, inspect_project
from stackwinnow.installer import InstallerError
from stackwinnow.recommend import recommend_tools
from stackwinnow.runner import run_command
from stackwinnow.state.lock import project_lock
from stackwinnow.supported import ToolSelection, supported_modes, validate_supported_host
from stackwinnow.verify import VerificationReport, check_project
from stackwinnow.workflow_state import (
    WorkflowError,
    WorkflowState,
    digest_at,
    snapshot,
    validate_transition,
    validate_verification_transition,
)


class WorkflowRequest(Contract):
    selections: tuple[ToolSelection, ...] = Field(min_length=1, max_length=4)
    assistant: Literal["codex"] = "codex"
    goals: tuple[str, ...] = ()
    model_preference: ModelPreference = "local"
    expectation: RelationshipExpectation | None = None

    @model_validator(mode="after")
    def unique_selection(self):
        ids = self.tool_ids
        if len(set(ids)) != len(ids):
            raise ValueError("Select each tool only once.")
        if ("graphify" in ids) != (self.expectation is not None):
            raise ValueError("Supply a relationship expectation exactly when Graphify is selected.")
        return self

    @property
    def tool_ids(self) -> list[str]:
        return [selection.tool_id for selection in self.selections]


class WorkflowPlan(Contract):
    schema_version: Literal[1] = 1
    recipe_revision: Literal[1] = 1
    workflow_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    project_root: str
    request: WorkflowRequest
    state: WorkflowState
    recipe_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    headroom: HeadroomPlan | None = None
    promptfoo: PromptfooPlan | None = None
    playwright: PlaywrightPlan | None = None
    graphify: GraphifyExecutionPlan | None = None
    graphify_reuse: bool = False
    graphify_configuration: ConfigPatch | None = None
    opik: OpikPlan | None = None
    langfuse: LangfusePlan | None = None
    ragas: RagasPlan | None = None
    trulens: TrulensPlan | None = None
    deepeval: DeepevalPlan | None = None
    inspect_ai: InspectAiPlan | None = None
    openlit: OpenlitPlan | None = None
    langchain: LangchainPlan | None = None
    litellm: LitellmPlan | None = None
    llmlingua: LlmlinguaPlan | None = None
    gptcache: GptcachePlan | None = None
    dspy: DspyPlan | None = None
    llama_index: LlamaIndexPlan | None = None
    pydantic_ai: PydanticAiPlan | None = None
    haystack: HaystackPlan | None = None
    langgraph: LanggraphPlan | None = None
    crewai: CrewaiPlan | None = None
    autogen: AutogenPlan | None = None
    smolagents: SmolagentsPlan | None = None
    checksum: str = Field(pattern=r"^[a-f0-9]{64}$")

    @property
    def phases(self) -> list[str]:
        phases = ["graphify-runtime"] if self.graphify else []
        phases += [
            name
            for name, plan in (
                ("headroom", self.headroom),
                ("promptfoo", self.promptfoo),
                ("playwright-mcp", self.playwright),
                ("opik", self.opik),
                ("langfuse", self.langfuse),
                ("ragas", self.ragas),
                ("trulens", self.trulens),
                ("deepeval", self.deepeval),
                ("inspect-ai", self.inspect_ai),
                ("openlit", self.openlit),
                ("langchain", self.langchain),
                ("litellm", self.litellm),
                ("llmlingua", self.llmlingua),
                ("gptcache", self.gptcache),
                ("dspy", self.dspy),
                ("llama-index", self.llama_index),
                ("pydantic-ai", self.pydantic_ai),
                ("haystack", self.haystack),
                ("langgraph", self.langgraph),
                ("crewai", self.crewai),
                ("autogen", self.autogen),
                ("smolagents", self.smolagents),
            )
            if plan
        ]
        if self.graphify:
            phases += ["graphify-index", "graphify-configure"]
        return phases + ["verify"]


class PhaseOutcome(Contract):
    phase: str
    status: Literal["succeeded", "failed", "blocked"]
    message: str


class WorkflowResult(Contract):
    schema_version: Literal[1] = 1
    workflow_id: str
    project_root: str
    dry_run: bool = False
    outcomes: list[PhaseOutcome] = Field(default_factory=list)
    stopped_phase: str | None = None
    verification: VerificationReport | None = None
    passive_status: VerificationReport | None = None
    completed_steps: list[str] = Field(default_factory=list)

    @property
    def ready(self) -> bool:
        return bool(
            not self.dry_run
            and self.stopped_phase is None
            and self.verification
            and self.verification.run_functional
            and self.verification.ready
            and self.passive_status is not None
            and _passive_current(self.passive_status)
        )

    def as_payload(self) -> dict:
        data = self.model_dump(mode="json")
        data["ready"] = self.ready
        data["status"] = "skipped" if self.dry_run else "succeeded" if self.ready else "blocked"
        data["partial_completion"] = bool(
            self.stopped_phase
            and (
                self.completed_steps or any(phase.status == "succeeded" for phase in self.outcomes)
            )
        )
        for name in ("verification", "passive_status"):
            report = getattr(self, name)
            if report is not None:
                data[name] = report.as_payload()
        return data


def _hash(value) -> str:
    return _digest(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def recipe_fingerprint() -> str:
    return _hash(
        {
            "revision": 1,
            "modes": [mode.model_dump() for mode in supported_modes()],
            "graphify_lock": LOCK_SHA256,
            "bridge": bridge_digest(),
            "headroom_fixture": headroom._FIXTURE_SHA256,
            "promptfoo_integrity": promptfoo.INTEGRITY,
            "promptfoo_provider": _digest(promptfoo._provider_path().read_bytes()),
            "playwright_packages": playwright_mcp.PACKAGES,
            "playwright_launcher": _digest(playwright_mcp.launcher().read_bytes()),
        }
    )


def _checksum(plan: WorkflowPlan) -> str:
    return _hash(plan.model_dump(mode="json", exclude={"checksum"}))


def explain_workflow(
    project_root: str | Path,
    *,
    goals: list[str] | None = None,
    model_preference: ModelPreference = "local",
) -> dict:
    """Read-only discovery; recommendations are never automatically selected."""
    inspection = inspect_project(
        project_root, goals=goals, assistant="codex", model_preference=model_preference
    )
    return {
        "schema_version": 1,
        "inspection": inspection.model_dump(mode="json"),
        "recommendations": recommend_tools(inspection).model_dump(mode="json"),
        "executable_modes": [mode.model_dump(mode="json") for mode in supported_modes()],
    }


def plan_workflow(project_root: str | Path, request: WorkflowRequest) -> WorkflowPlan:
    """Create a one-attempt preview without commands or managed state writes."""
    request = WorkflowRequest.model_validate(request.model_dump())
    root = _root(project_root)
    ids = request.tool_ids
    state = snapshot(root, ids)
    if "graphify" in ids and any(
        path not in state.sources
        for path in (request.expectation.caller_file, request.expectation.callee_file)
    ):
        raise WorkflowError(
            "Both explicitly expected relationship files must exist in the source snapshot."
        )
    graphify = None
    graph_config = None
    reuse = False
    if "graphify" in ids:
        reuse = state.record.receipt_for(STEP_ID) is not None
        if reuse:
            graphify, _ = validate_graphify_installation(root)
            plan_graphify_index(root, expectation=request.expectation, installation_plan=graphify)
        else:
            graphify = plan_graphify_execution(root, expectation=request.expectation)
        graph_config = _preview_graphify_configuration(root)
    plan = WorkflowPlan(
        workflow_id=uuid4().hex,
        project_root=str(root),
        request=request,
        state=state,
        recipe_sha256=recipe_fingerprint(),
        headroom=headroom.plan_headroom(root) if "headroom" in ids else None,
        promptfoo=promptfoo.plan_promptfoo(root) if "promptfoo" in ids else None,
        playwright=playwright_mcp.plan_playwright(root, assistant="codex")
        if "playwright-mcp" in ids
        else None,
        graphify=graphify,
        graphify_reuse=reuse,
        graphify_configuration=graph_config,
        opik=opik_adapter.plan_opik(root) if "opik" in ids else None,
        langfuse=langfuse_adapter.plan_langfuse(root) if "langfuse" in ids else None,
        ragas=ragas_adapter.plan_ragas(root) if "ragas" in ids else None,
        trulens=trulens_adapter.plan_trulens(root) if "trulens" in ids else None,
        deepeval=deepeval_adapter.plan_deepeval(root) if "deepeval" in ids else None,
        inspect_ai=inspect_ai_adapter.plan_inspect_ai(root) if "inspect-ai" in ids else None,
        openlit=openlit_adapter.plan_openlit(root) if "openlit" in ids else None,
        langchain=langchain_adapter.plan_langchain(root) if "langchain" in ids else None,
        litellm=litellm_adapter.plan_litellm(root) if "litellm" in ids else None,
        llmlingua=llmlingua_adapter.plan_llmlingua(root) if "llmlingua" in ids else None,
        gptcache=gptcache_adapter.plan_gptcache(root) if "gptcache" in ids else None,
        dspy=dspy_adapter.plan_dspy(root) if "dspy" in ids else None,
        llama_index=llama_index_adapter.plan_llama_index(root) if "llama-index" in ids else None,
        pydantic_ai=pydantic_ai_adapter.plan_pydantic_ai(root) if "pydantic-ai" in ids else None,
        haystack=haystack_adapter.plan_haystack(root) if "haystack" in ids else None,
        langgraph=langgraph_adapter.plan_langgraph(root) if "langgraph" in ids else None,
        crewai=crewai_adapter.plan_crewai(root) if "crewai" in ids else None,
        autogen=autogen_adapter.plan_autogen(root) if "autogen" in ids else None,
        smolagents=smolagents_adapter.plan_smolagents(root) if "smolagents" in ids else None,
        checksum="0" * 64,
    )
    if snapshot(root, ids) != state:
        raise WorkflowError("Project changed while planning; review a new plan.")
    plan.checksum = _checksum(plan)
    return plan


def _preview_graphify_configuration(root: Path) -> ConfigPatch:
    if record_for(root).receipt_for(CONFIGURE_STEP_ID) is not None:
        return owned_graphify_configuration(root)
    patch = plan_graphify_codex_server(root, graphify_server_settings(root))
    if not patch.edits:
        raise WorkflowError("Matching Graphify settings are foreign and cannot be adopted.")
    return patch


def load_workflow_plan(path: str | Path) -> WorkflowPlan:
    try:
        return WorkflowPlan.model_validate(read_json(Path(path)))
    except (OSError, ValueError, RuntimeError) as exc:
        raise WorkflowError("Invalid workflow plan; generate and review a new plan.") from exc


def _validate(plan: WorkflowPlan) -> Path:
    root = _root(plan.project_root)
    if str(root) != plan.project_root or _checksum(plan) != plan.checksum:
        raise WorkflowError("Workflow plan was changed; generate and review a new plan.")
    if recipe_fingerprint() != plan.recipe_sha256:
        raise WorkflowError("The supported recipes changed; review a new workflow plan.")
    journal = _journal_path(plan)
    directories(root, ".stackwinnow/workflows")
    if os.path.lexists(root / journal):
        raise WorkflowError(
            "This workflow was already attempted; create a new plan for reapplication."
        )
    if snapshot(root, plan.request.tool_ids) != plan.state:
        raise WorkflowError(
            "Project inputs, runtime, configuration or receipts changed; review a new plan."
        )
    leaves = {
        "headroom": plan.headroom,
        "promptfoo": plan.promptfoo,
        "playwright-mcp": plan.playwright,
        "graphify": plan.graphify,
        "opik": plan.opik,
        "langfuse": plan.langfuse,
        "ragas": plan.ragas,
        "trulens": plan.trulens,
        "deepeval": plan.deepeval,
        "inspect-ai": plan.inspect_ai,
        "openlit": plan.openlit,
        "langchain": plan.langchain,
        "litellm": plan.litellm,
        "llmlingua": plan.llmlingua,
        "gptcache": plan.gptcache,
        "dspy": plan.dspy,
        "llama-index": plan.llama_index,
        "pydantic-ai": plan.pydantic_ai,
        "haystack": plan.haystack,
        "langgraph": plan.langgraph,
        "crewai": plan.crewai,
        "autogen": plan.autogen,
        "smolagents": plan.smolagents,
    }
    if {name for name, leaf in leaves.items() if leaf is not None} != set(plan.request.tool_ids):
        raise WorkflowError("Workflow selections and reviewed adapters disagree.")
    for leaf in leaves.values():
        if leaf is not None and leaf.project_root != plan.project_root:
            raise WorkflowError("An adapter plan belongs to another project.")
    if plan.promptfoo and (
        plan.promptfoo.provider != "deterministic"
        or plan.promptfoo.scenario != "pass"
        or plan.promptfoo.model is not None
    ):
        raise WorkflowError("Unified workflows only execute deterministic promptfoo checks.")
    if plan.graphify:
        if any(
            path not in (plan.state.sources or {})
            for path in (plan.request.expectation.caller_file, plan.request.expectation.callee_file)
        ):
            raise WorkflowError(
                "Expected relationship files are absent from the reviewed source snapshot."
            )
        if plan.graphify_reuse != (plan.state.record.receipt_for(STEP_ID) is not None):
            raise WorkflowError("Graphify installation reuse does not match the reviewed state.")
        if _preview_graphify_configuration(root) != plan.graphify_configuration:
            raise WorkflowError("The reviewed Graphify configuration changed.")
        if plan.graphify_reuse:
            original, _ = validate_graphify_installation(root)
            if original != plan.graphify:
                raise WorkflowError("Graphify's original immutable installation recipe changed.")
            plan_graphify_index(
                root, expectation=plan.request.expectation, installation_plan=original
            )
        else:
            if plan.graphify.expectation != plan.request.expectation:
                raise WorkflowError("Graphify's explicit relationship changed.")
            apply_graphify_install(plan.graphify, dry_run=True)
    elif plan.graphify_reuse or plan.graphify_configuration is not None:
        raise WorkflowError("Unexpected Graphify configuration without a selection.")
    for leaf, apply in (
        (plan.headroom, headroom.apply_headroom),
        (plan.promptfoo, promptfoo.apply_promptfoo),
        (plan.playwright, playwright_mcp.apply_playwright),
    ):
        if leaf is not None:
            result = apply(leaf, dry_run=True)
            if result.status != OperationStatus.SKIPPED:
                raise WorkflowError(result.message)
    return root


def _prerequisites(plan: WorkflowPlan, runner) -> None:
    try:
        validate_supported_host(plan.request.tool_ids, plan.state.host)
    except ValueError as exc:
        raise WorkflowError(str(exc)) from exc
    patterns = {
        "node": r"v24\.\d+\.\d+",
        "npm": r"\d+\.\d+\.\d+",
        "codex": r"codex-cli " + re.escape(playwright_mcp.CODEX_VERSION),
    }
    for name, executable in plan.state.executables.items():
        if executable is None:
            raise WorkflowError(f"Missing {name}; install the prerequisite and review a new plan.")
        if name not in patterns:
            continue
        with tempfile.TemporaryDirectory(prefix="stackwinnow-preflight-") as scratch:
            environment = {key: scratch for key in ("HOME", "CODEX_HOME", "TMPDIR", "TMP", "TEMP")}
            environment.update(
                {
                    "NPM_CONFIG_USERCONFIG": str(Path(scratch) / "user.npmrc"),
                    "NPM_CONFIG_GLOBALCONFIG": str(Path(scratch) / "global.npmrc"),
                }
            )
            result = runner(
                [executable.path, "--version"], cwd=scratch, timeout=15, extra_env=environment
            )
        if not result.succeeded or not re.fullmatch(patterns[name], result.stdout.strip()):
            raise WorkflowError(
                f"A working supported {name} version is required; use 'workflow modes'."
            )


def _journal_path(plan: WorkflowPlan) -> str:
    return f".stackwinnow/workflows/{plan.workflow_id}.json"


def apply_workflow(
    plan: WorkflowPlan, *, dry_run: bool = False, command_runner=None
) -> WorkflowResult:
    """Apply exactly one reviewed attempt; stop and retain ownership on any failure."""
    checked = WorkflowPlan.model_validate(plan.model_dump())
    root = _validate(checked)
    result = WorkflowResult(
        workflow_id=checked.workflow_id, project_root=str(root), dry_run=dry_run
    )
    if dry_run:
        return result
    runner = command_runner or run_command
    _prerequisites(checked, runner)  # all external requirements before any installation
    expected = checked.state.model_copy(deep=True)

    def guard():
        if (
            recipe_fingerprint() != checked.recipe_sha256
            or snapshot(root, checked.request.tool_ids) != expected
        ):
            raise InstallerError(
                "Workflow state changed; stop and review a new plan. Partial state is retained."
            )

    def journal(phase: str | None):
        _publish(
            root,
            _journal_path(checked),
            json.dumps(
                {
                    "schema_version": 1,
                    "workflow_id": checked.workflow_id,
                    "plan_checksum": checked.checksum,
                    "active_phase": phase,
                    "result": result.as_payload(),
                },
                indent=2,
            ).encode(),
        )

    with project_lock(str(root)):
        guard()
        directories(root, ".stackwinnow/workflows", create=True)
        if os.path.lexists(root / _journal_path(checked)):
            raise WorkflowError("This workflow was already attempted; create a new plan.")
        journal(checked.phases[0])

    for phase in checked.phases:
        try:
            guard()
            with project_lock(str(root)):
                guard()
                journal(phase)
            tool_id = phase.split("-", 1)[0] if phase.startswith("graphify-") else phase
            patch = None
            if phase == "verify":
                result.verification = check_project(
                    root,
                    tool_ids=checked.request.tool_ids,
                    run_functional=True,
                    command_runner=runner,
                )
                # Verification is terminal: validate all non-receipt bindings, then
                # preserve unrelated receipt/history observations without adopting them.
                final = snapshot(root, checked.request.tool_ids)
                if final.model_dump(exclude={"record"}) != expected.model_dump(exclude={"record"}):
                    raise WorkflowError("Project inputs changed during final verification.")
                validate_verification_transition(
                    expected.record,
                    final.record,
                    result.verification,
                )
                expected.record = final.record.model_copy(deep=True)
                if not result.verification.ready:
                    raise WorkflowError("Fresh verification did not pass for every selected tool.")
                result.outcomes.append(
                    PhaseOutcome(
                        phase=phase,
                        status="succeeded",
                        message="Every selected tool passed fresh verification.",
                    )
                )
                continue
            if phase == "graphify-runtime":
                if checked.graphify_reuse:
                    original, _ = validate_graphify_installation(root)
                    if original != checked.graphify:
                        raise WorkflowError("The reviewed Graphify runtime changed.")
                    result.outcomes.append(
                        PhaseOutcome(
                            phase=phase,
                            status="succeeded",
                            message="Validated the original immutable Graphify installation.",
                        )
                    )
                    continue
                outcome = apply_graphify_install(
                    checked.graphify, command_runner=runner, before_execute=guard
                )
                success, steps = outcome.installed, {STEP_ID}
                if success:
                    original, _ = validate_graphify_installation(root)
                    if original != checked.graphify:
                        raise WorkflowError("Installed Graphify recipe differs from the review.")
            elif phase in ("headroom", "promptfoo", "playwright-mcp", "opik", "langfuse", "ragas", "trulens", "deepeval", "inspect-ai", "openlit", "langchain", "litellm", "llmlingua", "gptcache", "dspy", "llama-index", "pydantic-ai", "haystack", "langgraph", "crewai", "autogen", "smolagents"):
                leaf, apply = {
                    "headroom": (checked.headroom, headroom.apply_headroom),
                    "promptfoo": (checked.promptfoo, promptfoo.apply_promptfoo),
                    "playwright-mcp": (checked.playwright, playwright_mcp.apply_playwright),
                    "opik": (checked.opik, opik_adapter.apply_opik),
                    "langfuse": (checked.langfuse, langfuse_adapter.apply_langfuse),
                    "ragas": (checked.ragas, ragas_adapter.apply_ragas),
                    "trulens": (checked.trulens, trulens_adapter.apply_trulens),
                    "deepeval": (checked.deepeval, deepeval_adapter.apply_deepeval),
                    "inspect-ai": (checked.inspect_ai, inspect_ai_adapter.apply_inspect_ai),
                    "openlit": (checked.openlit, openlit_adapter.apply_openlit),
                    "langchain": (checked.langchain, langchain_adapter.apply_langchain),
                    "litellm": (checked.litellm, litellm_adapter.apply_litellm),
                    "llmlingua": (checked.llmlingua, llmlingua_adapter.apply_llmlingua),
                    "gptcache": (checked.gptcache, gptcache_adapter.apply_gptcache),
                    "dspy": (checked.dspy, dspy_adapter.apply_dspy),
                    "llama-index": (checked.llama_index, llama_index_adapter.apply_llama_index),
                    "pydantic-ai": (checked.pydantic_ai, pydantic_ai_adapter.apply_pydantic_ai),
                    "haystack": (checked.haystack, haystack_adapter.apply_haystack),
                    "langgraph": (checked.langgraph, langgraph_adapter.apply_langgraph),
                    "crewai": (checked.crewai, crewai_adapter.apply_crewai),
                    "autogen": (checked.autogen, autogen_adapter.apply_autogen),
                    "smolagents": (checked.smolagents, smolagents_adapter.apply_smolagents),
                }[phase]
                outcome = apply(leaf, command_runner=runner, before_execute=guard)
                success, steps = (
                    outcome.status == "succeeded",
                    {s.step_id for s in leaf.installation.steps},
                )
                if phase not in ("headroom", "opik", "langfuse", "ragas", "trulens", "deepeval", "inspect-ai", "openlit", "langchain", "litellm", "llmlingua", "gptcache", "dspy", "llama-index", "pydantic-ai", "haystack", "langgraph", "crewai", "autogen", "smolagents"):
                    patch = leaf.configuration
            elif phase == "graphify-index":
                index = plan_graphify_index(
                    root,
                    expectation=checked.request.expectation,
                    installation_plan=checked.graphify,
                )
                if {s.path: s.sha256 for s in index.sources} != expected.sources:
                    raise WorkflowError("Index inputs differ from the approved source state.")
                outcome = apply_graphify_index(index, command_runner=runner, before_execute=guard)
                success, steps = outcome.indexed, {INDEX_STEP_ID}
                if success:
                    provenance, _ = inspect_graphify_index(root)
                    if provenance.plan != index:
                        raise WorkflowError("The new index does not match the reviewed sources.")
                    expected.graph_artifacts = {
                        PROVENANCE_PATH: digest_at(root, PROVENANCE_PATH),
                        GRAPH_PATH: provenance.graph_sha256,
                    }
            else:
                configure = plan_graphify_configure(root)
                if configure.configuration.edits != checked.graphify_configuration.edits:
                    raise WorkflowError(
                        "The late Graphify configuration changes unreviewed settings."
                    )
                outcome = apply_graphify_configure(configure, before_execute=guard)
                success, steps = outcome.configured, {CONFIGURE_STEP_ID}
                # Reused configuration retains original ownership; its historical
                # whole-file digest must not overwrite today's expected Codex file.
                if checked.state.record.receipt_for(CONFIGURE_STEP_ID) is None:
                    patch = configure.configuration
            if outcome.record is not None:
                result.completed_steps.extend(
                    s.step_id
                    for s in outcome.record.steps
                    if s.step_id in steps and s.status == "succeeded"
                )
            if not success:
                raise WorkflowError(
                    getattr(
                        outcome,
                        "message",
                        "The adapter did not complete; inspect retained receipts.",
                    )
                )
            no_ops = set()
            if patch is not None and not patch.edits and patch.expected_file == patch.written_file:
                # Initial leaf validation proved existing ownership; the adapter's
                # fresh functional step rechecked it. Only its reviewed empty patch
                # may yield a skipped receipt; installation/function still must succeed.
                no_ops = {step_id for step_id in steps if step_id.endswith("-configure")}
            expected.record = validate_transition(
                expected.record, outcome.record, tool_id, steps, no_ops
            )
            if patch is not None:
                relative = patch.relative_path
                expected.configurations[relative] = patch.written_file.sha256
                if expected.sources is not None and phase == "promptfoo":
                    expected.sources[relative] = patch.written_file.sha256
            guard()
            result.outcomes.append(
                PhaseOutcome(
                    phase=phase,
                    status="succeeded",
                    message="Reviewed phase completed; ownership and inputs validated.",
                )
            )
        except (OSError, ValueError, RuntimeError, InstallerError) as exc:
            result.stopped_phase = phase
            result.outcomes.append(PhaseOutcome(phase=phase, status="blocked", message=str(exc)))
            break
    try:
        result.passive_status = check_project(root, tool_ids=checked.request.tool_ids)
        if not _passive_current(result.passive_status):
            raise WorkflowError(
                "Final passive status found incomplete or changed setup; inspect its checks."
            )
        current = snapshot(root, checked.request.tool_ids)
        if current != expected:
            raise WorkflowError("Project state changed during final status inspection.")
    except (OSError, ValueError, RuntimeError) as exc:
        result.stopped_phase = result.stopped_phase or "status"
        result.outcomes.append(PhaseOutcome(phase="status", status="blocked", message=str(exc)))
    with project_lock(str(root)):
        if result.stopped_phase is None:
            try:
                guard()
            except (OSError, ValueError, RuntimeError, InstallerError) as exc:
                result.stopped_phase = "status"
                result.outcomes.append(
                    PhaseOutcome(phase="status", status="blocked", message=str(exc))
                )
        journal(None)
    return result


def _passive_current(report: VerificationReport) -> bool:
    return all(
        check.status == "succeeded"
        if check.kind in ("installed", "configured")
        else check.status not in ("failed", "blocked")
        for tool in report.tools
        for check in tool.checks
    )

"""Local workbench API over the same discovery and lifecycle functions as the CLI."""

from __future__ import annotations

import json as _json
import os
import secrets
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from stackwinnow import __version__
from stackwinnow.adapters.graphify import RelationshipExpectation
from stackwinnow.catalog import (
    Category,
    EligibilityContext,
    Platform,
    evaluate_eligibility,
    filter_catalog,
    load_catalog,
)
from stackwinnow.detect import inspect_project
from stackwinnow.profiles import PortableProfile, export_profile, import_profile
from stackwinnow.recommend import recommend_tools
from stackwinnow.removal import apply_removal, plan_removal_lifecycle
from stackwinnow.report import build_report
from stackwinnow.runtime import inspect_environment
from stackwinnow.source_discovery import MAX_FILE_BYTES, MAX_FILES, MAX_TOTAL_BYTES, SUFFIXES
from stackwinnow.supported import select_tool, supported_modes
from stackwinnow.verify import check_project
from stackwinnow.workflow import WorkflowRequest, apply_workflow, plan_workflow

API_REVISION = 2
ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:5175",
    "http://127.0.0.1:5175",
}
app = FastAPI(title="StackWinnow Workbench", version=str(API_REVISION))
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(ORIGINS),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-StackWinnow-Token"],
)
_catalog = load_catalog()
_action_token = secrets.token_urlsafe(32)
_plans: dict[str, dict] = {}
_plan_lock = threading.Lock()


@app.middleware("http")
async def local_requests(request: Request, call_next):
    if request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return JSONResponse(
            {"detail": "This workbench accepts localhost requests only."}, status_code=403
        )
    origin = request.headers.get("origin")
    if origin and origin not in ORIGINS:
        return JSONResponse(
            {"detail": "Open the workbench from its local UI address."}, status_code=403
        )
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    return JSONResponse(
        {
            "detail": "Invalid request fields. Check selections, paths and JSON format.",
            "fields": [".".join(str(p) for p in e["loc"]) for e in exc.errors()],
        },
        status_code=422,
    )


@app.exception_handler(ValueError)
async def invalid_operation(request, exc):
    message = (
        "Invalid selections or document. Generate a fresh plan."
        if isinstance(exc, ValidationError)
        else str(exc)
    )
    return JSONResponse({"detail": message}, status_code=422)


@app.exception_handler(OSError)
async def file_error(request, exc):
    return JSONResponse(
        {"detail": "Could not access project files. Check the path, permissions and file types."},
        status_code=422,
    )


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectInput(Input):
    project_root: str = Field(min_length=1)


def root_for(req: ProjectInput) -> Path:
    root = Path(req.project_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise HTTPException(422, "Choose an existing project directory.")
    return root


class DiscoveryInput(ProjectInput):
    goals: list[str] = Field(default_factory=list)
    assistant: str | None = None
    model_preference: Literal["local", "hosted", "any"] | None = None
    platform: Platform | None = None
    config_path: str | None = None
    scan_source: bool = True
    selected_tools: list[str] = Field(default_factory=list)


def inspection_for(req: DiscoveryInput):
    validate_discovery(req)
    return inspect_project(
        root_for(req),
        goals=req.goals,
        assistant=req.assistant,
        model_preference=req.model_preference,
        config_path=req.config_path,
        selected_tools=req.selected_tools,
        scan_source=req.scan_source,
    )


def validate_discovery(req: DiscoveryInput):
    assistants = {a for tool in _catalog.tools for a in tool.supported_assistants}
    if req.assistant is not None and req.assistant not in assistants:
        raise HTTPException(
            422, "Choose a documented coding assistant from the compatibility targets."
        )


def inspection_payload(result):
    return {**result.model_dump(mode="json"), "complete": result.complete}


def recommendation_payload(result):
    return {
        **result.model_dump(mode="json"),
        "complete": result.complete,
        "inspection": inspection_payload(result.inspection),
    }


@app.get("/api/meta")
def metadata():
    return {
        "api_revision": API_REVISION,
        "version": __version__,
        "action_token": _action_token,
        "engine": "Local static source analysis",
        "provider_calls": False,
        "assistants": sorted({a for tool in _catalog.tools for a in tool.supported_assistants}),
        "assistant_effect": "Changes catalog compatibility checks. Does not select an AI model or change source findings. Managed client setup currently targets Codex.",
        "platforms": [p.value for p in Platform],
        "categories": [c.value for c in Category],
        "modes": [m.model_dump(mode="json") for m in supported_modes()],
        "scan": {
            "extensions": sorted(SUFFIXES),
            "max_files": MAX_FILES,
            "max_file_bytes": MAX_FILE_BYTES,
            "max_total_bytes": MAX_TOTAL_BYTES,
        },
        "features": [
            "source-discovery",
            "file-coverage",
            "catalog",
            "workflow-plan",
            "workflow-apply",
            "verification",
            "removal",
            "profiles",
            "reports",
            "environment",
        ],
    }


@app.post("/api/inspect")
def inspect(req: DiscoveryInput):
    return inspection_payload(inspection_for(req))


@app.post("/api/recommend")
def recommend(req: DiscoveryInput):
    return recommendation_payload(
        recommend_tools(inspection_for(req), catalog=_catalog, platform=req.platform)
    )


@app.post("/api/workflow/discover")
def discover(req: DiscoveryInput):
    result = recommend(req)
    return {
        "inspection": result["inspection"],
        "recommendations": result,
        "executable_modes": workflow_modes(),
    }


@app.get("/api/catalog")
def catalog(
    category: Category | None = None,
    q: str = "",
    assistant: str | None = None,
    platform: Platform | None = None,
):
    context = EligibilityContext(
        assistant=assistant,
        platform=platform,
        registered_adapters=[m.tool_id for m in supported_modes()],
    )
    entries = filter_catalog(_catalog, category=category)
    modes = {m.tool_id: m.model_dump(mode="json") for m in supported_modes()}
    return {
        "tools": [
            {
                **t.model_dump(mode="json"),
                "eligibility": evaluate_eligibility(t, context).model_dump(mode="json"),
                "managed_mode": modes.get(t.tool_id),
            }
            for t in entries
            if q.casefold() in (t.name + " " + t.description + " " + t.tool_id).casefold()
        ]
    }


@app.get("/api/catalog/{tool_id}")
def tool_detail(tool_id: str, assistant: str | None = None, platform: Platform | None = None):
    try:
        tool = _catalog.get(tool_id)
    except KeyError:
        raise HTTPException(404, "Tool not found.") from None
    context = EligibilityContext(
        assistant=assistant,
        platform=platform,
        registered_adapters=[m.tool_id for m in supported_modes()],
    )
    return {
        **tool.model_dump(mode="json"),
        "eligibility": evaluate_eligibility(tool, context).model_dump(mode="json"),
    }


@app.get("/api/workflow/modes")
def workflow_modes():
    return [m.model_dump(mode="json") for m in supported_modes()]


class SelectionInput(ProjectInput):
    tool_ids: list[str] = Field(min_length=1, max_length=4)


def selections(req):
    selected = tuple(select_tool(t) for t in req.tool_ids)
    if len(set(req.tool_ids)) != len(req.tool_ids):
        raise HTTPException(422, "Select each tool once.")
    return selected


class PlanInput(SelectionInput):
    goals: list[str] = Field(default_factory=list)
    model_preference: Literal["local", "hosted", "any"] = "local"
    expectation: RelationshipExpectation | None = None


def remember(kind: str, document, phases: list[str] | None = None):
    now = time.monotonic()
    with _plan_lock:
        for key in list(_plans):
            if now - _plans[key]["created"] > 3600:
                del _plans[key]
        if len(_plans) >= 100:
            raise HTTPException(
                409, "Too many review plans. Restart the local backend to clear them."
            )
        key = secrets.token_urlsafe(24)
        _plans[key] = {"kind": kind, "document": document, "created": now, "attempted": False}
    return {
        "plan_id": key,
        "kind": kind,
        "document": document.model_dump(mode="json"),
        "phases": phases or [],
        "created_at": datetime.now(UTC).isoformat(),
        "expires_in_seconds": 3600,
    }


def reviewed(key: str, kind: str | None = None, *, consume: bool = False):
    with _plan_lock:
        saved = _plans.get(key)
        if not saved or time.monotonic() - saved["created"] > 3600:
            raise HTTPException(
                409, "Review plan expired or backend restarted. Generate a fresh plan."
            )
        if kind and saved["kind"] != kind:
            raise HTTPException(422, "This action requires a different kind of review plan.")
        if consume:
            if saved["attempted"]:
                raise HTTPException(409, "This plan was already attempted. Review a fresh plan.")
            saved["attempted"] = True
        return saved


def require_action(request: Request):
    if not secrets.compare_digest(request.headers.get("x-stackwinnow-token", ""), _action_token):
        raise HTTPException(403, "Refresh the local workbench before running this action.")


@app.post("/api/workflow/plan")
def workflow_plan(req: PlanInput):
    plan = plan_workflow(
        root_for(req),
        WorkflowRequest(
            selections=selections(req),
            goals=tuple(req.goals),
            model_preference=req.model_preference,
            expectation=req.expectation,
        ),
    )
    return remember("workflow", plan, plan.phases)


class ApplyInput(Input):
    plan_id: str
    confirm: bool = False
    dry_run: bool = False


@app.post("/api/workflow/apply")
def workflow_apply(req: ApplyInput, request: Request):
    require_action(request)
    if not req.dry_run and not req.confirm:
        raise HTTPException(422, "Review the plan and confirm application first.")
    plan = reviewed(req.plan_id, "workflow", consume=not req.dry_run)["document"]
    return apply_workflow(plan, dry_run=req.dry_run).as_payload()


@app.post("/api/workflow/status")
def workflow_status(req: SelectionInput):
    selections(req)
    return check_project(root_for(req), tool_ids=req.tool_ids).as_payload()


class CheckInput(SelectionInput):
    confirm: bool = False


@app.post("/api/workflow/check")
def workflow_check(req: CheckInput, request: Request):
    require_action(request)
    if not req.confirm:
        raise HTTPException(422, "Confirm running functional checks on the selected tools.")
    selections(req)
    return check_project(root_for(req), tool_ids=req.tool_ids, run_functional=True).as_payload()


@app.post("/api/removal/plan")
def removal_plan(req: SelectionInput):
    selections(req)
    return remember("removal", plan_removal_lifecycle(root_for(req), req.tool_ids))


@app.post("/api/removal/apply")
def removal_apply(req: ApplyInput, request: Request):
    require_action(request)
    if not req.dry_run and not req.confirm:
        raise HTTPException(422, "Review retained/removed paths and confirm removal first.")
    plan = reviewed(req.plan_id, "removal", consume=not req.dry_run)["document"]
    return apply_removal(plan, dry_run=req.dry_run).model_dump(mode="json")


class ProfileExport(Input):
    plan_id: str


@app.post("/api/profiles/export")
def profile_export(req: ProfileExport):
    return export_profile(reviewed(req.plan_id, "workflow")["document"]).model_dump(mode="json")


class ProfileImport(ProjectInput):
    profile: PortableProfile


@app.post("/api/profiles/import")
def profile_import(req: ProfileImport):
    plan = import_profile(req.profile, root_for(req))
    return remember("workflow", plan, plan.phases)


@app.post("/api/reports")
def report(req: DiscoveryInput):
    # Use the report implementation to preserve consistent CLI Markdown and JSON.
    validate_discovery(req)
    result = build_report(
        root_for(req),
        goals=req.goals,
        assistant=req.assistant,
        selected_tools=req.selected_tools,
        model_preference=req.model_preference,
        config_path=req.config_path,
        platform=req.platform,
        scan_source=req.scan_source,
    )
    return {"markdown": result.to_markdown(), "json": result.to_payload()}


@app.post("/api/environment")
def environment(req: ProjectInput):
    profile, diagnostics = inspect_environment(str(root_for(req)))
    return {
        "profile": profile.model_dump(mode="json"),
        "diagnostics": [d.model_dump(mode="json") for d in diagnostics],
        "modes": workflow_modes(),
    }


class SuggestInput(Input):
    goals: list[str] = Field(default_factory=list)


@app.post("/api/suggest")
def suggest(req: SuggestInput):
    """Ask Claude to suggest tools from the catalog based on stated goals."""
    if not req.goals:
        return {"tool_ids": [], "reasoning": "No goals provided.", "assisted": False}

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    if not api_key:
        return {"tool_ids": [], "reasoning": "ANTHROPIC_API_KEY not configured.", "assisted": False}

    try:
        import anthropic

        catalog_lines = [
            f"- {t.tool_id} ({t.category.value}): {t.description}" for t in _catalog.tools
        ]
        catalog_text = "\n".join(catalog_lines)
        goals_text = ", ".join(req.goals)

        prompt = (
            "You help developers choose AI tooling for their projects.\n\n"
            f"Available tools:\n{catalog_text}\n\n"
            f"Developer goals: {goals_text}\n\n"
            "Which tools from the catalog best match these goals?\n"
            'Return ONLY a JSON object: {"tool_ids": [...], "reasoning": "..."}\n'
            "Use only tool_ids exactly as listed above."
        )

        client_kwargs: dict = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        client = anthropic.Anthropic(**client_kwargs)
        model = os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", "claude-haiku-4-5")
        message = client.messages.create(
            model=model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )

        text = message.content[0].text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3].strip()

        result = _json.loads(text)
        valid_ids = {t.tool_id for t in _catalog.tools}
        tool_ids = [tid for tid in result.get("tool_ids", []) if tid in valid_ids]

        return {"tool_ids": tool_ids, "reasoning": result.get("reasoning", ""), "assisted": True}

    except Exception as exc:
        return {"tool_ids": [], "reasoning": f"AI suggestion unavailable: {exc}", "assisted": False}

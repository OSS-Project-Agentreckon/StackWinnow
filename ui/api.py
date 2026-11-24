"""FastAPI backend for the StackWinnow web UI."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from stackwinnow.catalog import (
    CatalogError,
    Category,
    EligibilityContext,
    evaluate_eligibility,
    filter_catalog,
    load_catalog,
)
from stackwinnow.detect import InspectionError, inspect_project
from stackwinnow.recommend import RecommendationError, recommend_tools
from stackwinnow.supported import select_tool, supported_modes
from stackwinnow.workflow import WorkflowError, WorkflowRequest, explain_workflow, plan_workflow

app = FastAPI(title="StackWinnow UI", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_catalog = load_catalog()


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


@app.get("/api/catalog")
def list_catalog(category: str | None = None, q: str | None = None):
    cat = category.lower() if category else None
    entries = filter_catalog(_catalog, category=Category(cat) if cat else None)
    if q:
        q_lower = q.lower()
        entries = [
            e
            for e in entries
            if q_lower in e.tool_id or q_lower in e.name.lower() or q_lower in e.description.lower()
        ]
    context = EligibilityContext(registered_adapters=[m.tool_id for m in supported_modes()])
    return {
        "count": len(entries),
        "tools": [
            {
                "tool_id": e.tool_id,
                "name": e.name,
                "category": e.category,
                "availability": e.availability,
                "description": e.description,
                "eligibility": evaluate_eligibility(e, context).model_dump(),
            }
            for e in entries
        ],
    }


@app.get("/api/catalog/{tool_id}")
def get_tool(tool_id: str, platform: str | None = None, assistant: str | None = None):
    try:
        entry = _catalog.get(tool_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_id}' not found.")
    context = EligibilityContext(
        platform=platform,
        assistant=assistant,
        registered_adapters=[m.tool_id for m in supported_modes()],
    )
    eligibility = evaluate_eligibility(entry, context)
    return {**entry.model_dump(), "eligibility": eligibility.model_dump()}


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------


class InspectRequest(BaseModel):
    project_root: str
    goals: list[str] = []
    assistant: str | None = None
    model_preference: Literal["local", "hosted", "any"] | None = None


@app.post("/api/inspect")
def inspect(req: InspectRequest):
    root = Path(req.project_root).expanduser().resolve()
    if not root.exists():
        raise HTTPException(status_code=422, detail=f"Path does not exist: {root}")
    try:
        result = inspect_project(
            root,
            goals=req.goals or None,
            assistant=req.assistant,
            model_preference=req.model_preference,
        )
    except InspectionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Recommend
# ---------------------------------------------------------------------------


class RecommendRequest(BaseModel):
    project_root: str
    goals: list[str] = []
    assistant: str | None = None
    model_preference: Literal["local", "hosted", "any"] | None = None


@app.post("/api/recommend")
def recommend(req: RecommendRequest):
    root = Path(req.project_root).expanduser().resolve()
    if not root.exists():
        raise HTTPException(status_code=422, detail=f"Path does not exist: {root}")
    try:
        inspection = inspect_project(
            root,
            goals=req.goals or None,
            assistant=req.assistant,
            model_preference=req.model_preference,
        )
        result = recommend_tools(inspection, catalog=_catalog)
    except (InspectionError, RecommendationError, CatalogError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


@app.get("/api/workflow/modes")
def workflow_modes():
    return [
        {
            "tool_id": m.tool_id,
            "mode": m.mode,
            "version": m.version,
            "description": m.description,
            "requirements": list(m.requirements),
        }
        for m in supported_modes()
    ]


class WorkflowDiscoverRequest(BaseModel):
    project_root: str
    goals: list[str] = []
    model_preference: Literal["local", "hosted", "any"] = "local"


@app.post("/api/workflow/discover")
def workflow_discover(req: WorkflowDiscoverRequest):
    root = Path(req.project_root).expanduser().resolve()
    if not root.exists():
        raise HTTPException(status_code=422, detail=f"Path does not exist: {root}")
    try:
        data = explain_workflow(root, goals=req.goals, model_preference=req.model_preference)
    except (InspectionError, CatalogError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return data


class WorkflowPlanRequest(BaseModel):
    project_root: str
    tool_ids: list[str]
    goals: list[str] = []
    model_preference: Literal["local", "hosted", "any"] = "local"


@app.post("/api/workflow/plan")
def workflow_plan(req: WorkflowPlanRequest):
    root = Path(req.project_root).expanduser().resolve()
    if not root.exists():
        raise HTTPException(status_code=422, detail=f"Path does not exist: {root}")
    try:
        selections = tuple(select_tool(t) for t in req.tool_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        request = WorkflowRequest(
            selections=selections,
            goals=tuple(req.goals),
            model_preference=req.model_preference,
        )
        plan = plan_workflow(root, request)
    except (WorkflowError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return plan.model_dump(mode="json")

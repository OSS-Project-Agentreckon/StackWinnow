"""Generic plan/apply CLI for all pip library-mode adapters."""

from __future__ import annotations

import json
from pathlib import Path

from stackwinnow.adapters import autogen as autogen_adapter
from stackwinnow.adapters import crewai as crewai_adapter
from stackwinnow.adapters import deepeval as deepeval_adapter
from stackwinnow.adapters import dspy as dspy_adapter
from stackwinnow.adapters import gptcache as gptcache_adapter
from stackwinnow.adapters import haystack as haystack_adapter
from stackwinnow.adapters import inspect_ai as inspect_ai_adapter
from stackwinnow.adapters import langchain as langchain_adapter
from stackwinnow.adapters import langfuse as langfuse_adapter
from stackwinnow.adapters import langgraph as langgraph_adapter
from stackwinnow.adapters import litellm as litellm_adapter
from stackwinnow.adapters import llama_index as llama_index_adapter
from stackwinnow.adapters import llmlingua as llmlingua_adapter
from stackwinnow.adapters import openlit as openlit_adapter
from stackwinnow.adapters import opik as opik_adapter
from stackwinnow.adapters import pydantic_ai as pydantic_ai_adapter
from stackwinnow.adapters import ragas as ragas_adapter
from stackwinnow.adapters import smolagents as smolagents_adapter
from stackwinnow.adapters import trulens as trulens_adapter

_ADAPTERS = {
    "opik":        (opik_adapter.plan_opik,          opik_adapter.apply_opik),
    "langfuse":    (langfuse_adapter.plan_langfuse,  langfuse_adapter.apply_langfuse),
    "ragas":       (ragas_adapter.plan_ragas,        ragas_adapter.apply_ragas),
    "trulens":     (trulens_adapter.plan_trulens,    trulens_adapter.apply_trulens),
    "deepeval":    (deepeval_adapter.plan_deepeval,  deepeval_adapter.apply_deepeval),
    "inspect-ai":  (inspect_ai_adapter.plan_inspect_ai, inspect_ai_adapter.apply_inspect_ai),
    "openlit":     (openlit_adapter.plan_openlit,    openlit_adapter.apply_openlit),
    "langchain":   (langchain_adapter.plan_langchain, langchain_adapter.apply_langchain),
    "litellm":     (litellm_adapter.plan_litellm,    litellm_adapter.apply_litellm),
    "llmlingua":   (llmlingua_adapter.plan_llmlingua, llmlingua_adapter.apply_llmlingua),
    "gptcache":    (gptcache_adapter.plan_gptcache,  gptcache_adapter.apply_gptcache),
    "dspy":        (dspy_adapter.plan_dspy,          dspy_adapter.apply_dspy),
    "llama-index": (llama_index_adapter.plan_llama_index, llama_index_adapter.apply_llama_index),
    "pydantic-ai": (pydantic_ai_adapter.plan_pydantic_ai, pydantic_ai_adapter.apply_pydantic_ai),
    "haystack":    (haystack_adapter.plan_haystack,  haystack_adapter.apply_haystack),
    "langgraph":   (langgraph_adapter.plan_langgraph, langgraph_adapter.apply_langgraph),
    "crewai":      (crewai_adapter.plan_crewai,      crewai_adapter.apply_crewai),
    "autogen":     (autogen_adapter.plan_autogen,    autogen_adapter.apply_autogen),
    "smolagents":  (smolagents_adapter.plan_smolagents, smolagents_adapter.apply_smolagents),
}


def add_library_parser(commands):
    parser = commands.add_parser(
        "library",
        help="Plan or apply a pip library-mode adapter for any supported AI tool.",
        allow_abbrev=False,
    )
    actions = parser.add_subparsers(dest="library_command", required=True)

    plan_parser = actions.add_parser(
        "plan",
        help="Preview the installation steps for a library-mode tool.",
        allow_abbrev=False,
    )
    plan_parser.add_argument("project_root", help="Existing project directory.")
    plan_parser.add_argument(
        "--tool",
        required=True,
        choices=sorted(_ADAPTERS),
        metavar="TOOL_ID",
        help="Library tool to plan. Choices: " + ", ".join(sorted(_ADAPTERS)),
    )
    plan_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a reviewable JSON plan; redirect to a file, review, then pass to 'apply'.",
    )

    apply_parser = actions.add_parser(
        "apply",
        help="Execute a reviewed library plan (installs into a managed venv).",
        allow_abbrev=False,
    )
    apply_parser.add_argument("plan_file", help="JSON plan file saved from 'library plan --json'.")
    apply_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Revalidate without installing or writing files.",
    )
    apply_parser.add_argument("--json", action="store_true", help="Emit structured results.")


def library_command(args, parser) -> int:
    action = args.library_command

    if action == "plan":
        plan_fn, _ = _ADAPTERS[args.tool]
        try:
            plan = plan_fn(args.project_root)
        except (OSError, ValueError) as exc:
            parser.exit(2, f"error: {exc}\n")
            return 2

        if args.json:
            print(plan.model_dump_json(indent=2))
        else:
            steps = plan.installation.steps if hasattr(plan.installation, "steps") else []
            print(f"Project : {plan.project_root}")
            print(f"Tool    : {plan.tool_id} {plan.version}  (mode: {plan.mode})")
            print(f"Steps   : {len(steps)}")
            for step in steps:
                print(f"  {step.description}")
            print()
            print("Save the plan and apply it:")
            print(f"  stackwinnow library plan {plan.project_root} --tool {plan.tool_id} --json > plan.json")
            print("  stackwinnow library apply plan.json")
        return 0

    # apply
    try:
        raw = Path(args.plan_file).read_text(encoding="utf-8")
        data = json.loads(raw)
        tool_id = data.get("tool_id")
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, f"error: Cannot read plan file: {exc}\n")
        return 2

    if tool_id not in _ADAPTERS:
        parser.exit(2, f"error: Plan tool_id '{tool_id}' is not a supported library adapter.\n")
        return 2

    _, apply_fn = _ADAPTERS[tool_id]
    plan_fn, _ = _ADAPTERS[tool_id]

    # Reconstruct the plan via the adapter's own Plan model
    try:
        plan = plan_fn.__module__
        import importlib
        mod = importlib.import_module(plan_fn.__module__)
        plan_cls_name = tool_id.replace("-", "_").title().replace("_", "") + "Plan"
        # handle names like LlamaIndex → LlamaIndexPlan, PydanticAi → PydanticAiPlan
        plan_cls = getattr(mod, plan_cls_name, None)
        if plan_cls is None:
            # fallback: find by scanning module attrs
            for attr in dir(mod):
                if attr.lower() == (tool_id.replace("-", "") + "plan").lower():
                    plan_cls = getattr(mod, attr)
                    break
        if plan_cls is None:
            parser.exit(2, f"error: Cannot locate Plan class for '{tool_id}'.\n")
            return 2
        plan_obj = plan_cls.model_validate_json(raw)
    except (OSError, ValueError, Exception) as exc:
        parser.exit(2, f"error: Invalid plan file: {exc}\n")
        return 2

    result = apply_fn(plan_obj, dry_run=args.dry_run)

    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        print(f"Status : {result.status}")
        print(f"Message: {result.message}")
        for op in result.results:
            print(f"  [{op.status}] {op.message}")
    return 0 if result.status in ("succeeded", "skipped") else 1

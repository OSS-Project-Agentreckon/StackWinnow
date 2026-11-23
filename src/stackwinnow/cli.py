"""Tool discovery, project recommendations, and explicit adapter commands."""

import argparse
import json
from collections.abc import Sequence

from pydantic import ValidationError

from stackwinnow import __version__
from stackwinnow.adapters.graphify import GraphifyError, plan_graphify
from stackwinnow.adapters.graphify_install import (
    apply_graphify_install,
    load_graphify_install_plan,
)
from stackwinnow.adapters.graphify_plan import (
    load_graphify_execution_plan,
    load_relationship_expectation,
    plan_graphify_execution,
)
from stackwinnow.adapters.promptfoo import (
    PromptfooError,
    apply_promptfoo,
    load_promptfoo_plan,
    plan_promptfoo,
)
from stackwinnow.catalog import (
    Catalog,
    CatalogEntry,
    CatalogError,
    Category,
    Eligibility,
    EligibilityContext,
    Platform,
    evaluate_eligibility,
    filter_catalog,
    load_catalog,
)
from stackwinnow.configure import ConfigurationError
from stackwinnow.detect import InspectionError, InspectionResult, inspect_project
from stackwinnow.plan import PreflightError
from stackwinnow.recommend import RecommendationError, RecommendationResult, recommend_tools
from stackwinnow.verify import VerificationError, check_project


def _playwright(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from stackwinnow.adapters.playwright_mcp import (
        PlaywrightError,
        apply_playwright,
        load_playwright_plan,
        plan_playwright,
    )

    try:
        if args.playwright_command == "plan":
            plan = plan_playwright(args.project_root, assistant=args.assistant)
            if args.json:
                print(plan.model_dump_json(indent=2))
            else:
                print(f"Project: {plan.project_root}")
                print(f"Pinned release: Playwright MCP {plan.version}")
                print(f"Assistant: {plan.assistant}; Node: {plan.node}")
                for step in plan.installation.steps:
                    print(f"  {step.description}")
                print(
                    "Use --json to save a reviewable plan; "
                    "'playwright-mcp apply PLAN.json' applies it."
                )
            return 0
        plan = load_playwright_plan(args.plan_file)
        result = apply_playwright(plan, dry_run=args.dry_run)
        if args.json:
            print(result.model_dump_json(indent=2))
        else:
            print(f"{result.status}: {result.message}")
            for operation in result.results:
                print(f"  [{operation.status}] {operation.message}")
        return 0 if result.status in ("succeeded", "skipped") else 1
    except ValidationError:
        parser.exit(2, "error: Invalid Playwright MCP plan or assistant selection.\n")
        return 2
    except (PlaywrightError, ConfigurationError, CatalogError) as exc:
        parser.exit(2, f"error: {exc}\n")
        return 2
    except (OSError, ValueError):
        parser.exit(2, "error: Invalid Playwright plan or project state.\n")
        return 2


def _check_project(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    try:
        report = check_project(
            args.project_root,
            tool_ids=args.tool,
            run_functional=args.run_functional,
            provider=args.provider,
            scenario=args.scenario,
            allow_provider_usage=args.allow_provider_usage,
        )
    except (VerificationError, CatalogError) as exc:
        parser.exit(2, f"error: {exc}\n")
        return 2
    if args.json:
        print(json.dumps(report.as_payload(), indent=2))
    else:
        print(f"Project: {report.project_root}")
        print(f"Verification: {report.status}; ready: {'yes' if report.ready else 'no'}")
        for tool in report.tools:
            print(f"{tool.tool_id} (connection scope: {tool.connection_scope})")
            for check in tool.checks:
                print(f"  [{check.status}] {check.kind}: {check.message}")
                for evidence in check.evidence:
                    print(f"    Evidence: {evidence.source}")
    return 0 if report.ready else 1


def _graphify(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.graphify_command in ("index-plan", "index"):
        return _graphify_index(args, parser)
    if args.graphify_command == "apply":
        try:
            result = apply_graphify_install(
                load_graphify_install_plan(args.plan_file), dry_run=args.dry_run
            )
        except GraphifyError as exc:
            parser.exit(2, f"error: {exc}\n")
            return 2
        if args.json:
            print(result.model_dump_json(indent=2))
        else:
            print("Graphify scope: local installation only; assistant ready: no")
            for operation in result.results:
                print(f"  [{operation.status}] {operation.message}")
            for limitation in result.limitations:
                print(f"  Pending: {limitation}")
        return 0 if result.dry_run or result.installed else 1
    if args.graphify_command in ("execution-plan", "validate-plan"):
        return _graphify_execution_plan(args, parser)
    try:
        plan = plan_graphify(args.project_root, platform=args.platform, assistant=args.assistant)
    except GraphifyError as exc:
        parser.exit(2, f"error: {exc}\n")
        return 2
    except (ValidationError, PreflightError, CatalogError, OSError):
        parser.exit(2, "error: Cannot preview Graphify; check the catalog and project state.\n")
        return 2
    if args.json:
        print(
            plan.model_dump_json(
                indent=2,
                exclude={
                    "installation": {"schema_version"},
                    "preflight": {"schema_version"},
                },
            )
        )
    else:
        print(f"Project: {plan.project_root}")
        print(f"Graphify preview: {plan.artifact.distribution}=={plan.artifact.version}")
        print(f"Target: {plan.target_platform} / {plan.assistant}")
        print(f"Graph output: {plan.graph_path}")
        print("Apply: unavailable (preview only)")
        for blocker in plan.blockers:
            print(f"  {blocker}")
        print("Preflight:")
        for check in plan.preflight.checks:
            print(f"  [{check.status}] {check.message}")
        for note in plan.notes:
            print(note)
        print("Use --json to inspect command arguments. No project files were changed.")
    return 0


def _graphify_index(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from stackwinnow.adapters.graphify_index import (
        apply_graphify_index,
        load_graphify_index_plan,
        plan_graphify_index,
    )

    try:
        if args.graphify_command == "index-plan":
            result = plan_graphify_index(
                args.project_root,
                expectation=load_relationship_expectation(args.expectation),
                installation_plan=load_graphify_install_plan(args.installation_plan)
                if args.installation_plan
                else None,
            )
            print(result.model_dump_json(indent=2))
            return 0
        result = apply_graphify_index(
            load_graphify_index_plan(args.plan_file), dry_run=args.dry_run
        )
        if args.json:
            print(result.model_dump_json(indent=2))
        else:
            for operation in result.results:
                print(f"[{operation.status}] {operation.message}")
        return 0 if result.dry_run or result.indexed else 1
    except GraphifyError as exc:
        parser.exit(2, f"error: {exc}\n")
        return 2


def _graphify_execution_plan(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    try:
        if args.graphify_command == "validate-plan":
            plan = load_graphify_execution_plan(args.plan_file)
        else:
            plan = plan_graphify_execution(
                args.project_root, expectation=load_relationship_expectation(args.expectation)
            )
    except GraphifyError as exc:
        parser.exit(2, f"error: {exc}\n")
        return 2
    if args.json:
        print(plan.model_dump_json(indent=2))
    else:
        print(f"Project: {plan.project_root}")
        print(f"Execution preparation: {plan.target}; {len(plan.packages)} locked wheels")
        print("Scope: local install/index; intended assistant: Codex (not configured)")
        print("Install only: graphify apply PLAN.json --install-only; full apply is pending")
        print(f"Planned environment: {plan.environment_path}")
        print(f"Planned graph: {plan.graph_path}")
        for operation in plan.operations:
            print(f"  Operation: {operation}")
        for source in plan.sources:
            print(f"  Relationship source: {source.path} (SHA-256 {source.sha256})")
        for blocker in plan.blockers:
            print(f"  Blocked: {blocker}")
        print("No commands, downloads, or project writes were performed.")
    return 0


def _headroom(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from stackwinnow.adapters.headroom import (
        HeadroomError,
        HeadroomPlan,
        apply_headroom,
        plan_headroom,
    )

    try:
        if args.headroom_command == "plan":
            plan = plan_headroom(args.project_root)
            if args.json:
                print(plan.model_dump_json(indent=2))
            else:
                print(f"Project: {plan.project_root}")
                print(f"headroom {plan.version} (Apache-2.0); mode: {plan.mode}")
                for step in plan.installation.steps:
                    print(f"  {step.description}")
                print(
                    "Use --json to save a reviewable plan; 'headroom apply PLAN.json' applies it."
                )
            return 0
        with open(args.plan_file, encoding="utf-8") as stream:
            plan = HeadroomPlan.model_validate_json(stream.read())
        result = apply_headroom(plan, dry_run=args.dry_run)
        if args.json:
            print(result.model_dump_json(indent=2))
        else:
            print(f"{result.status}: {result.message}")
            for operation in result.results:
                print(f"  [{operation.status}] {operation.message}")
        return 0 if result.status in ("succeeded", "skipped") else 1
    except HeadroomError as exc:
        parser.exit(2, f"error: {exc}\n")
        return 2
    except (OSError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
        return 2


def _promptfoo(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    try:
        if args.promptfoo_command == "plan":
            plan = plan_promptfoo(
                args.project_root, provider=args.provider, model=args.model, scenario=args.scenario
            )
            if args.json:
                print(plan.model_dump_json(indent=2))
            else:
                print(f"Project: {plan.project_root}")
                print(f"Pinned release: promptfoo {plan.version} (MIT)")
                print(f"Provider: {plan.provider}; scenario: {plan.scenario}")
                if plan.provider == "openai":
                    print(
                        "Applying this plan sends the two fixture prompts to OpenAI and may incur charges."
                    )
                for step in plan.installation.steps:
                    print(f"  {step.description}")
                print(
                    "Use --json to save a reviewable plan; 'promptfoo apply PLAN.json' applies it."
                )
            return 0
        plan = load_promptfoo_plan(args.plan_file)
        result = apply_promptfoo(
            plan, dry_run=args.dry_run, allow_provider_usage=args.allow_provider_usage
        )
        if args.json:
            print(result.model_dump_json(indent=2))
        else:
            print(f"{result.status}: {result.message}")
            for operation in result.results:
                print(f"  [{operation.status}] {operation.message}")
        return 0 if result.status in ("succeeded", "skipped") else 1
    except ValidationError:
        parser.exit(2, "error: Invalid promptfoo plan or provider/model selection.\n")
    except (PromptfooError, ConfigurationError, CatalogError) as exc:
        parser.exit(2, f"error: {exc}\n")
    except OSError:
        parser.exit(2, "error: Cannot read the project or selected plan file.\n")


def _read_inspection(
    args: argparse.Namespace, *, catalog: Catalog | None = None
) -> InspectionResult:
    return inspect_project(
        args.project_root,
        goals=args.goal,
        assistant=args.assistant,
        selected_tools=args.tool,
        model_preference=args.model_preference,
        config_path=args.config,
        catalog=catalog,
    )


def _inspect(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    try:
        result = _read_inspection(args)
    except (InspectionError, CatalogError) as exc:
        parser.exit(2, f"error: {exc}\n")
        return 2
    except ValidationError:
        # Validation errors may include input values. Do not echo arbitrary input.
        parser.exit(2, "error: Supply nonempty goals and valid assistant/tool IDs.\n")
        return 2
    if args.json:
        payload = result.model_dump(
            mode="json",
            exclude={
                "profile": {"schema_version"},
                "diagnostics": {"__all__": {"schema_version"}},
            },
        )
        print(json.dumps({**payload, "complete": result.complete}, indent=2))
    else:
        _show_inspection(result)
    return 0 if result.complete else 1


def _recommend(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    try:
        catalog = load_catalog()
        result = recommend_tools(
            _read_inspection(args, catalog=catalog), catalog=catalog, platform=args.platform
        )
    except (InspectionError, CatalogError, RecommendationError) as exc:
        parser.exit(2, f"error: {exc}\n")
        return 2
    except ValidationError:
        parser.exit(2, "error: Supply nonempty goals and valid assistant/tool IDs.\n")
        return 2
    if args.json:
        payload = result.model_dump(
            mode="json",
            exclude={
                "inspection": {
                    "schema_version": True,
                    "profile": {"schema_version"},
                    "diagnostics": {"__all__": {"schema_version"}},
                },
            },
        )
        print(json.dumps({**payload, "complete": result.complete}, indent=2))
    else:
        _show_recommendations(result)
    return 0 if result.complete else 1


def _show_recommendations(result: RecommendationResult) -> None:
    _show_inspection(result.inspection)
    print(f"Target platform: {result.target_platform or 'unknown'}")
    print("Recommendations:")
    for item in result.recommendations:
        label = (
            "selected" if item.selected else "declared" if item.already_declared else "goal match"
        )
        print(f"  {item.name} ({item.tool_id}) [{label}]: {item.description}")
        for reason in item.reasons:
            detail = (
                reason.fact_key + ": " + ", ".join(reason.values)
                if reason.fact_key
                else "; ".join(reason.goals)
            )
            print(f"    Why: {reason.message}" + (f" ({detail})" if detail else ""))
            if reason.matched_capabilities:
                print("      Matched capabilities: " + ", ".join(reason.matched_capabilities))
        print("    Setup: " + ("eligible" if item.eligibility.installable else "unavailable"))
        for reason in item.eligibility.reasons:
            print(f"      {reason.message}")
        if item.alternatives:
            print("    Alternatives to compare: " + ", ".join(item.alternatives))
        if item.conflicts_with:
            print("    Conflicts with: " + ", ".join(item.conflicts_with))
        for limitation in item.limitations:
            print(f"    Limitation: {limitation}")
    if result.relationships:
        print("Relationships:")
    for relationship in result.relationships:
        print(f"  {relationship.kind}: " + " / ".join(relationship.tools))
    for note in result.notes:
        print(note)
    if result.unmatched_goals:
        print("Unmatched goals: " + "; ".join(result.unmatched_goals))


def _add_inspection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("project_root", help="Existing project directory.")
    parser.add_argument("--goal", action="append", help="Explicit goal; repeat for multiple goals.")
    parser.add_argument("--assistant", help="Explicit assistant ID; omitted means unknown.")
    parser.add_argument("--tool", action="append", help="Catalog tool ID; repeat to select tools.")
    parser.add_argument("--model-preference", choices=["local", "hosted", "any"])
    parser.add_argument("--config", help="Project-relative JSON file; read mcpServers names only.")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON.")


def _show_inspection(result: InspectionResult) -> None:
    profile = result.profile
    print(f"Project: {profile.project_root}")
    print(f"Inspection: {'complete' if result.complete else 'incomplete'}")
    print(f"Assistant: {profile.assistant or 'unknown'}")
    print("Goals: " + ("; ".join(profile.goals) or "not supplied"))
    print("Selected tools: " + (", ".join(result.selected_tools) or "none"))
    print(f"Model preference: {result.model_preference or 'not supplied'}")
    print("Declared facts:")
    if not profile.facts:
        print("  No supported declarations found; project details remain unknown.")
    for key, values in sorted(profile.facts.items()):
        print(f"  {key}: {', '.join(values) if values else '(explicitly empty)'}")
    print("Evidence:")
    for evidence in profile.evidence:
        print(f"  {evidence.source}: {evidence.detail}")
    print("Diagnostics:")
    for item in result.diagnostics:
        print(f"  [{item.status}] {item.message}")
    print("Declarations and selections do not establish installation or functional readiness.")


def _add_display_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Emit structured JSON.")
    parser.add_argument(
        "--platform",
        choices=[item.value for item in Platform],
        help="Target operating system for eligibility explanations; does not scan the machine.",
    )
    parser.add_argument(
        "--assistant", help="Target assistant ID, for example claude-code or codex."
    )


def _view(tool: CatalogEntry, eligibility: Eligibility) -> dict[str, object]:
    return {
        "tool": tool.model_dump(mode="json", exclude={"schema_version"}),
        "eligibility": eligibility.model_dump(mode="json"),
    }


def _show(tool: CatalogEntry, context: EligibilityContext) -> None:
    eligibility = evaluate_eligibility(tool, context)
    print(f"{tool.name} ({tool.tool_id})")
    print(tool.description)
    print(f"Category: {tool.category}")
    print(f"Repository: {tool.repository}")
    print(f"License: {tool.license or 'unknown'} ({tool.license_review})")
    print(f"License scope: {tool.license_scope}")
    print(f"Source review: {tool.reviewed_on}")
    print(f"Availability: {tool.availability}")
    print(f"Installation-ready: {'yes' if eligibility.installable else 'no'}")
    for reason in eligibility.reasons:
        print(f"  [{reason.code}] {reason.message}")
    print("Prerequisites:")
    for requirement in tool.prerequisites:
        print(f"  - {requirement}")
    print(f"Compatibility: {tool.compatibility_notes}")
    print("Documented platforms: " + (", ".join(tool.supported_platforms) or "unknown"))
    print("Documented assistants: " + (", ".join(tool.supported_assistants) or "unknown"))
    print("Limitations:")
    for limitation in tool.limitations:
        print(f"  - {limitation}")
    print(
        "Recorded conflicts: "
        + (", ".join(tool.conflicts) or "none recorded; not compatibility proof")
    )
    print("Related alternatives: " + (", ".join(tool.alternatives) or "none recorded"))
    print("Sources:")
    for source in tool.sources:
        print(f"  {source.kind}: {source.url}")


def main(argv: Sequence[str] | None = None) -> int:
    """Discover tools, preview Graphify, and explicitly plan/apply promptfoo setup."""
    parser = argparse.ArgumentParser(
        prog="stackwinnow",
        description="Choose suitable open-source AI tools for your project.",
        epilog="Catalog discovery is read-only. Promptfoo execution requires the shared runner.",
        allow_abbrev=False,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command")
    graphify = commands.add_parser(
        "graphify",
        help="Preview Graphify or explicitly install its locked local packages.",
        allow_abbrev=False,
    )
    graphify_commands = graphify.add_subparsers(dest="graphify_command", required=True)
    graphify_plan = graphify_commands.add_parser("plan", allow_abbrev=False)
    graphify_plan.add_argument("project_root", help="Existing project directory.")
    graphify_plan.add_argument("--platform", required=True, choices=["macos"])
    graphify_plan.add_argument("--assistant", required=True, choices=["codex"])
    graphify_plan.add_argument(
        "--json", action="store_true", help="Emit a read-only recipe preview."
    )
    execution_plan = graphify_commands.add_parser(
        "execution-plan",
        allow_abbrev=False,
        help="Prepare a locked macOS arm64/Python 3.11 plan for explicit install-only apply.",
    )
    execution_plan.add_argument("project_root", help="Existing project directory.")
    execution_plan.add_argument(
        "--expectation",
        required=True,
        help="JSON file identifying an expected source relationship.",
    )
    execution_plan.add_argument("--json", action="store_true", help="Emit the reviewable plan.")
    validate_plan = graphify_commands.add_parser(
        "validate-plan", allow_abbrev=False, help="Recheck a saved plan without executing it."
    )
    validate_plan.add_argument("plan_file", help="Saved execution-plan JSON file.")
    validate_plan.add_argument("--json", action="store_true", help="Emit the revalidated plan.")
    graphify_apply = graphify_commands.add_parser("apply", allow_abbrev=False)
    graphify_apply.add_argument("plan_file", help="Saved execution-plan JSON file.")
    graphify_apply.add_argument(
        "--install-only",
        action="store_true",
        required=True,
        help="Explicitly select package installation only; no indexing or Codex setup.",
    )
    graphify_apply.add_argument("--dry-run", action="store_true")
    graphify_apply.add_argument("--json", action="store_true")
    index_plan = graphify_commands.add_parser(
        "index-plan",
        allow_abbrev=False,
        help="Review current runtime and source inputs for initial indexing or reindexing.",
    )
    index_plan.add_argument("project_root")
    index_plan.add_argument("--expectation", required=True)
    index_plan.add_argument(
        "--installation-plan",
        help="Original execution-plan JSON for a legacy installation manifest.",
    )
    index_plan.add_argument(
        "--json", action="store_true", help="Emit the reviewable JSON plan (default)."
    )
    index_apply = graphify_commands.add_parser(
        "index",
        allow_abbrev=False,
        help="Apply a reviewed index plan; reuse only current graph evidence.",
    )
    index_apply.add_argument("plan_file")
    index_apply.add_argument("--dry-run", action="store_true")
    index_apply.add_argument("--json", action="store_true")
    checking = commands.add_parser(
        "check",
        help="Verify selected tools without installing or changing their configuration.",
        allow_abbrev=False,
    )
    checking.add_argument("project_root", help="Existing project directory.")
    checking.add_argument(
        "--tool",
        action="append",
        required=True,
        help="Catalog tool ID to check; repeat for multiple tools.",
    )
    checking.add_argument(
        "--run-functional",
        action="store_true",
        help="Execute a fresh check and record results; never install or configure.",
    )
    checking.add_argument(
        "--provider", choices=["deterministic", "openai"], default="deterministic"
    )
    checking.add_argument(
        "--scenario",
        choices=["pass", "fail"],
        default="pass",
        help="Optional deliberate failure for the local functional check.",
    )
    checking.add_argument(
        "--allow-provider-usage",
        action="store_true",
        help="Permit the configured hosted provider calls and possible charges.",
    )
    checking.add_argument(
        "--json", action="store_true", help="Emit observations and derived readiness."
    )
    playwright = commands.add_parser(
        "playwright-mcp",
        help="Plan/apply project-scoped Playwright MCP for Codex.",
        allow_abbrev=False,
    )
    playwright_commands = playwright.add_subparsers(dest="playwright_command", required=True)
    playwright_plan = playwright_commands.add_parser("plan", allow_abbrev=False)
    playwright_plan.add_argument("project_root")
    playwright_plan.add_argument("--assistant", required=True, choices=["codex"])
    playwright_plan.add_argument("--json", action="store_true")
    playwright_apply = playwright_commands.add_parser("apply", allow_abbrev=False)
    playwright_apply.add_argument("plan_file")
    playwright_apply.add_argument("--dry-run", action="store_true")
    playwright_apply.add_argument("--json", action="store_true")
    headroom = commands.add_parser(
        "headroom",
        help="Plan/apply headroom-ai library installation and compression verification.",
        allow_abbrev=False,
    )
    headroom_commands = headroom.add_subparsers(dest="headroom_command", required=True)
    headroom_plan = headroom_commands.add_parser("plan", allow_abbrev=False)
    headroom_plan.add_argument("project_root", help="Existing project directory.")
    headroom_plan.add_argument("--json", action="store_true", help="Emit a reviewable plan.")
    headroom_apply = headroom_commands.add_parser("apply", allow_abbrev=False)
    headroom_apply.add_argument("plan_file", help="Saved JSON plan from 'headroom plan --json'.")
    headroom_apply.add_argument(
        "--dry-run", action="store_true", help="Revalidate without installing or running."
    )
    headroom_apply.add_argument("--json", action="store_true", help="Emit structured results.")
    promptfoo = commands.add_parser(
        "promptfoo", help="Preview and apply a pinned project evaluation.", allow_abbrev=False
    )
    promptfoo_commands = promptfoo.add_subparsers(dest="promptfoo_command", required=True)
    promptfoo_plan = promptfoo_commands.add_parser("plan", allow_abbrev=False)
    promptfoo_plan.add_argument("project_root", help="Existing project directory.")
    promptfoo_plan.add_argument(
        "--provider", choices=["deterministic", "openai"], default="deterministic"
    )
    promptfoo_plan.add_argument(
        "--model", help="Explicit OpenAI model ID for the optional hosted path."
    )
    promptfoo_plan.add_argument("--scenario", choices=["pass", "fail"], default="pass")
    promptfoo_plan.add_argument(
        "--json", action="store_true", help="Emit a plan suitable for saving and applying."
    )
    promptfoo_apply = promptfoo_commands.add_parser("apply", allow_abbrev=False)
    promptfoo_apply.add_argument("plan_file", help="Saved JSON plan from 'promptfoo plan --json'.")
    promptfoo_apply.add_argument(
        "--dry-run", action="store_true", help="Revalidate and describe the plan without changes."
    )
    promptfoo_apply.add_argument(
        "--allow-provider-usage",
        action="store_true",
        help="Explicitly permit the selected hosted provider calls and their possible charges.",
    )
    promptfoo_apply.add_argument(
        "--json", action="store_true", help="Emit structured results and receipts."
    )
    inspection = commands.add_parser(
        "inspect", help="Read project manifests and record explicit goals.", allow_abbrev=False
    )
    _add_inspection_arguments(inspection)
    recommendations = commands.add_parser(
        "recommend",
        help="Explain tools matching project declarations and goals.",
        allow_abbrev=False,
    )
    _add_inspection_arguments(recommendations)
    recommendations.add_argument(
        "--platform",
        choices=[item.value for item in Platform],
        help="Declared target OS for eligibility; does not inspect the host.",
    )
    catalog_parser = commands.add_parser(
        "catalog", help="Browse the reviewed tool catalog.", allow_abbrev=False
    )
    catalog_commands = catalog_parser.add_subparsers(dest="catalog_command")
    listing = catalog_commands.add_parser(
        "list", help="List tools, optionally filtering the catalog.", allow_abbrev=False
    )
    listing.add_argument("--category", choices=[item.value for item in Category])
    listing.add_argument(
        "--installable", action="store_true", help="Only show installation-ready tools."
    )
    _add_display_arguments(listing)
    showing = catalog_commands.add_parser(
        "show", help="Explain one tool and its setup eligibility.", allow_abbrev=False
    )
    showing.add_argument("tool_id")
    _add_display_arguments(showing)
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "inspect":
        return _inspect(args, parser)
    if args.command == "recommend":
        return _recommend(args, parser)
    if args.command == "playwright-mcp":
        return _playwright(args, parser)
    if args.command == "headroom":
        return _headroom(args, parser)
    if args.command == "promptfoo":
        return _promptfoo(args, parser)
    if args.command == "graphify":
        return _graphify(args, parser)
    if args.command == "check":
        return _check_project(args, parser)
    if args.catalog_command is None:
        catalog_parser.print_help()
        return 0
    try:
        context = EligibilityContext(platform=args.platform, assistant=args.assistant)
        catalog = load_catalog()
        if args.catalog_command == "show":
            try:
                tool = catalog.get(args.tool_id)
            except KeyError:
                parser.error(f"Unknown tool '{args.tool_id}'. Use 'stackwinnow catalog list'.")
                return 2
            if args.json:
                print(
                    json.dumps(
                        {"schema_version": 1, **_view(tool, evaluate_eligibility(tool, context))},
                        indent=2,
                    )
                )
            else:
                _show(tool, context)
        else:
            entries = filter_catalog(
                catalog,
                category=Category(args.category) if args.category else None,
            )
            eligibility = (
                {tool.tool_id: evaluate_eligibility(tool, context) for tool in entries}
                if args.json or args.installable
                else {}
            )
            if args.installable:
                entries = [tool for tool in entries if eligibility[tool.tool_id].installable]
            if args.json:
                print(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "count": len(entries),
                            "tools": [_view(tool, eligibility[tool.tool_id]) for tool in entries],
                        },
                        indent=2,
                    )
                )
            elif not entries:
                print("No tools match. Use 'catalog show TOOL_ID' for eligibility explanations.")
            else:
                print(f"{'ID':<18} {'CATEGORY':<20} {'AVAILABILITY':<18} DESCRIPTION")
                for tool in entries:
                    print(
                        f"{tool.tool_id:<18} {tool.category:<20} {tool.availability:<18} {tool.description}"
                    )
                print(
                    f"\n{len(entries)} tools. Catalog membership does not mean installation readiness."
                )
    except (CatalogError, ValidationError) as exc:
        parser.exit(2, f"error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

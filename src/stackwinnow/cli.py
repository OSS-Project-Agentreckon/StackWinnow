"""Read-only catalog discovery and project inspection commands."""

import argparse
import json
from collections.abc import Sequence

from pydantic import ValidationError

from stackwinnow import __version__
from stackwinnow.catalog import (
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
from stackwinnow.detect import InspectionError, InspectionResult, inspect_project


def _inspect(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    try:
        result = inspect_project(
            args.project_root,
            goals=args.goal,
            assistant=args.assistant,
            selected_tools=args.tool,
            model_preference=args.model_preference,
            config_path=args.config,
        )
    except (InspectionError, CatalogError) as exc:
        parser.exit(2, f"error: {exc}\n")
    except ValidationError:
        # Validation errors may include input values. Do not echo arbitrary input.
        parser.exit(2, "error: Supply nonempty goals and valid assistant/tool IDs.\n")
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
    """Discover tools without modifying the project or installing dependencies."""
    parser = argparse.ArgumentParser(
        prog="stackwinnow",
        description="Choose suitable open-source AI tools for your project.",
        epilog="Catalog discovery is read-only. Installation is not available yet.",
        allow_abbrev=False,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command")
    inspection = commands.add_parser(
        "inspect", help="Read project manifests and record explicit goals.", allow_abbrev=False
    )
    inspection.add_argument("project_root", help="Existing project directory.")
    inspection.add_argument(
        "--goal", action="append", help="Explicit goal; repeat for multiple goals."
    )
    inspection.add_argument("--assistant", help="Explicit assistant ID; omitted means unknown.")
    inspection.add_argument(
        "--tool", action="append", help="Catalog tool ID; repeat to select tools."
    )
    inspection.add_argument("--model-preference", choices=["local", "hosted", "any"])
    inspection.add_argument(
        "--config", help="Project-relative JSON file; read mcpServers names only."
    )
    inspection.add_argument("--json", action="store_true", help="Emit structured JSON.")
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

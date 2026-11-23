"""The `stackwinnow report` command: a read-only Markdown/JSON project report."""

import argparse
import json

from pydantic import ValidationError

from stackwinnow.catalog import CatalogError, Platform
from stackwinnow.detect import InspectionError
from stackwinnow.recommend import RecommendationError
from stackwinnow.report import ReportError, build_report
from stackwinnow.verify import VerificationError


def add_report_parser(commands) -> None:
    parser = commands.add_parser(
        "report",
        help="Summarize a project's AI tooling as a Markdown or JSON report.",
        allow_abbrev=False,
    )
    parser.add_argument("project_root", help="Existing project directory.")
    parser.add_argument("--goal", action="append", help="Explicit goal; repeat for multiple goals.")
    parser.add_argument("--assistant", help="Explicit assistant ID; omitted means unknown.")
    parser.add_argument("--tool", action="append", help="Catalog tool ID; repeat to select tools.")
    parser.add_argument("--model-preference", choices=["local", "hosted", "any"])
    parser.add_argument("--config", help="Project-relative JSON file; read mcpServers names only.")
    parser.add_argument(
        "--platform",
        choices=[item.value for item in Platform],
        help="Declared target OS for eligibility; does not inspect the host.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Include a passive verification section for the selected tools.",
    )
    parser.add_argument("--json", action="store_true", help="Emit the structured JSON report.")


def report_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.check and not args.tool:
        parser.exit(2, "error: --check needs at least one --tool.\n")
        return 2
    try:
        report = build_report(
            args.project_root,
            goals=args.goal,
            assistant=args.assistant,
            selected_tools=args.tool,
            model_preference=args.model_preference,
            config_path=args.config,
            platform=args.platform,
            include_verification=args.check,
        )
    except (
        InspectionError,
        RecommendationError,
        CatalogError,
        VerificationError,
        ReportError,
    ) as exc:
        parser.exit(2, f"error: {exc}\n")
        return 2
    except ValidationError:
        # Validation errors may include input values. Do not echo arbitrary input.
        parser.exit(2, "error: Supply nonempty goals and valid assistant/tool IDs.\n")
        return 2
    except OSError:
        parser.exit(2, "error: Cannot read the selected project.\n")
        return 2
    if args.json:
        print(json.dumps(report.to_payload(), indent=2))
    else:
        print(report.to_markdown())
    return 0 if report.ready else 1

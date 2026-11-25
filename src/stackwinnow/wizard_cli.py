"""Argparse registration and entry point for the interactive installation wizard."""

from __future__ import annotations

import argparse

from stackwinnow.wizard import run_wizard


def add_wizard_parser(commands) -> None:
    parser = commands.add_parser(
        "wizard",
        help="Interactively select and install AI tools for your project.",
        allow_abbrev=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Inspect the project, show recommended tools grouped by category,\n"
            "let you pick which to install, then install with progress output."
        ),
    )
    parser.add_argument("project_root", help="Existing project directory.")
    parser.add_argument(
        "--goal",
        action="append",
        default=[],
        metavar="GOAL",
        help=(
            "Goal to pass to the recommender; repeat for multiple. "
            "Defaults: evaluation, track costs, compress context, model routing."
        ),
    )


def wizard_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    goals = args.goal or None
    return run_wizard(args.project_root, goals=goals)

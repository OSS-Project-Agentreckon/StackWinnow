"""Verification of explicitly selected tools, separate from install preflight."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from stackwinnow.adapters.promptfoo import CommandRunner, Provider, Scenario
from stackwinnow.catalog import load_catalog
from stackwinnow.verify.models import (
    CheckKind,
    CheckStatus,
    ToolVerification,
    VerificationCheck,
    VerificationOptions,
    VerificationReport,
)

__all__ = [
    "CheckKind",
    "CheckStatus",
    "ToolVerification",
    "VerificationCheck",
    "VerificationError",
    "VerificationReport",
    "check_project",
]


class VerificationError(ValueError):
    """Invalid project or explicit verification selection."""


def check_project(
    project_root: str | Path,
    *,
    tool_ids: Sequence[str],
    run_functional: bool = False,
    provider: Provider = "deterministic",
    scenario: Scenario = "pass",
    allow_provider_usage: bool = False,
    command_runner: CommandRunner | None = None,
) -> VerificationReport:
    """Inspect without commands/writes unless a fresh functional check is requested."""
    from stackwinnow.verify.graphify import check_graphify
    from stackwinnow.verify.headroom import check_headroom
    from stackwinnow.verify.playwright_mcp import check_playwright
    from stackwinnow.verify.promptfoo import check_promptfoo

    try:
        options = VerificationOptions(
            tool_ids=tuple(tool_ids),
            run_functional=run_functional,
            provider=provider,
            scenario=scenario,
            allow_provider_usage=allow_provider_usage,
        )
    except ValidationError as exc:
        raise VerificationError("Supply unique tool IDs and valid verification options.") from exc
    catalog = load_catalog()
    for tool_id in options.tool_ids:
        try:
            catalog.get(tool_id)
        except KeyError as exc:
            raise VerificationError(f"Unknown tool '{tool_id}'. Use 'catalog list'.") from exc
    try:
        root = Path(project_root).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("not a directory")
    except (OSError, RuntimeError, ValueError) as exc:
        raise VerificationError("Select an existing project directory.") from exc
    results = []
    for tool_id in options.tool_ids:
        if tool_id == "promptfoo":
            results.append(check_promptfoo(root, options, command_runner=command_runner))
        elif tool_id == "headroom":
            results.append(check_headroom(root, options, command_runner=command_runner))
        elif tool_id == "graphify":
            results.append(check_graphify(root, options, command_runner=command_runner))
        elif tool_id == "playwright-mcp":
            results.append(check_playwright(root, options, command_runner=command_runner))
        else:
            results.append(
                ToolVerification(
                    tool_id=tool_id,
                    connection_scope="unknown",
                    checks=tuple(
                        VerificationCheck(
                            kind=kind,
                            status=CheckStatus.BLOCKED,
                            code="verifier-unavailable",
                            message="This catalog tool has no verification adapter yet.",
                        )
                        for kind in CheckKind
                    ),
                )
            )
    return VerificationReport(
        project_root=str(root),
        checked_at=datetime.now(UTC).isoformat(),
        run_functional=options.run_functional,
        tools=tuple(results),
    )

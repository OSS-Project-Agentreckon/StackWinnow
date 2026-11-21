"""Read-only setup inspection or an explicit fresh Codex browser fixture check."""

from pathlib import Path

from stackwinnow.adapters import playwright_mcp as adapter
from stackwinnow.adapters._managed import ManagedStateError
from stackwinnow.contracts import EvidenceRef
from stackwinnow.runner import run_command
from stackwinnow.verify.models import CheckKind, CheckStatus, ToolVerification, VerificationCheck
from stackwinnow.verify.playwright_client import run_client_check


def check_playwright(root: Path, options, *, command_runner=None) -> ToolVerification:
    checks = {
        kind: VerificationCheck(
            kind=kind,
            status=CheckStatus.NOT_RUN,
            code="fresh-check-required",
            message="Request --run-functional for fresh Codex client evidence.",
        )
        for kind in CheckKind
    }

    def set_check(kind, status, code, message, source=None):
        checks[kind] = VerificationCheck(
            kind=kind,
            status=status,
            code=code,
            message=message,
            evidence=(EvidenceRef(source=str(source), detail=message),) if source else (),
        )

    try:
        plan = adapter.plan_playwright(root, assistant="codex")
        installed, configured = adapter.inspect_setup(root, plan.node)
        for kind, ready, source in (
            (
                CheckKind.INSTALLED,
                installed,
                root / adapter.NODE / "node_modules/.package-lock.json",
            ),
            (CheckKind.CONFIGURED, configured, root / ".codex/config.toml"),
        ):
            set_check(
                kind,
                CheckStatus.SUCCEEDED if ready else CheckStatus.BLOCKED,
                "owned-setup-verified" if ready else "setup-missing",
                "Owned setup metadata matches the pinned recipe; runtime health requires execution."
                if ready
                else "Run playwright-mcp plan/apply to create the missing owned setup.",
                source if ready else None,
            )
        if options.run_functional:
            if not installed or not configured:
                raise adapter.PlaywrightError(
                    "Install and configure Playwright before a functional check."
                )
            runner = command_runner or run_command
            _, codex = adapter.prerequisites(root, plan.node, runner)
            with adapter.operation_lock(root):
                # Repeat validation after prerequisite commands and lock acquisition.
                if adapter._build(root, plan.run_id) != plan or adapter.inspect_setup(
                    root, plan.node
                ) != (True, True):
                    raise adapter.PlaywrightError(
                        "Owned setup changed before the functional check."
                    )
                registration = adapter.settings(root, plan.node)
                result = run_client_check(
                    root,
                    registration,
                    codex,
                    runner=runner,
                    scenario=options.scenario,
                )
                adapter.revalidate_client_setup(root, plan.node, registration)
            for kind, key in (
                (CheckKind.CONNECTED, "connected"),
                (CheckKind.FUNCTIONAL, "functional"),
            ):
                set_check(
                    kind,
                    CheckStatus.SUCCEEDED if result[key] else CheckStatus.FAILED,
                    "codex-client-fixture",
                    result["message"],
                    result["evidence_path"],
                )
    except (OSError, ValueError) as exc:
        message = (
            str(exc)
            if isinstance(exc, ManagedStateError)
            else "Setup paths, configuration or receipts need inspection before execution."
        )
        for kind in CheckKind:
            set_check(kind, CheckStatus.BLOCKED, "setup-blocked", message)
    return ToolVerification(
        tool_id="playwright-mcp", connection_scope="assistant", checks=tuple(checks.values())
    )

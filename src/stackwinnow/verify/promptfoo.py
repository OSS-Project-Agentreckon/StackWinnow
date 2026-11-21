"""Observe owned promptfoo state and optionally execute a fresh evaluation."""

from __future__ import annotations

import os
import re
from pathlib import Path

from pydantic import ValidationError

from stackwinnow.adapters import promptfoo as adapter
from stackwinnow.configure import ConfigurationError
from stackwinnow.contracts import EvidenceRef
from stackwinnow.verify.models import (
    CheckKind,
    CheckStatus,
    ToolVerification,
    VerificationCheck,
    VerificationOptions,
)


def _check(kind, status, code, message, source: Path | None = None) -> VerificationCheck:
    return VerificationCheck(
        kind=kind,
        status=status,
        code=code,
        message=message,
        evidence=() if source is None else (EvidenceRef(source=str(source), detail=message),),
    )


def _initial(options: VerificationOptions) -> dict[CheckKind, VerificationCheck]:
    checks = {
        kind: _check(
            kind, CheckStatus.BLOCKED, "state-unavailable", "Project setup could not be checked."
        )
        for kind in CheckKind
    }
    checks[CheckKind.CONNECTED] = (
        _check(
            CheckKind.CONNECTED,
            CheckStatus.NOT_APPLICABLE,
            "standalone-provider",
            "The local fixture runs standalone; no assistant or hosted connection is claimed.",
        )
        if options.provider == "deterministic"
        else _check(
            CheckKind.CONNECTED,
            CheckStatus.NOT_RUN,
            "provider-not-checked",
            "Connectivity to the configured OpenAI provider has not been tested.",
        )
    )
    checks[CheckKind.FUNCTIONAL] = _check(
        CheckKind.FUNCTIONAL,
        CheckStatus.NOT_RUN,
        "fresh-check-required",
        "Use --run-functional for a fresh evaluation; previous reports are historical evidence.",
    )
    return checks


def _model_from_config(config: dict, options: VerificationOptions) -> str | None:
    if options.provider == "deterministic":
        return None
    try:
        provider = config["providers"][0]["id"]
        match = re.fullmatch(r"openai:chat:([a-zA-Z0-9][a-zA-Z0-9._-]{0,79})", provider)
    except (KeyError, IndexError, TypeError):
        match = None
    if match is None:
        raise adapter.PromptfooError("The owned OpenAI profile has no supported explicit model.")
    return match.group(1)


def _inspect(root: Path, options: VerificationOptions):
    checks = _initial(options)
    model = None
    try:
        if adapter._root(root) != root:
            raise adapter.PromptfooError("The selected project now resolves elsewhere.")
        record = adapter._record(root)
    except (adapter.PromptfooError, OSError, ValueError) as exc:
        message = (
            str(exc)
            if isinstance(exc, adapter.PromptfooError)
            else "Project receipts or paths are unreadable or invalid."
        )
        for kind in (CheckKind.INSTALLED, CheckKind.CONFIGURED, CheckKind.FUNCTIONAL):
            checks[kind] = _check(kind, CheckStatus.BLOCKED, "unsafe-or-invalid-state", message)
        if options.provider == "openai":
            checks[CheckKind.CONNECTED] = _check(
                CheckKind.CONNECTED, CheckStatus.BLOCKED, "unsafe-or-invalid-state", message
            )
        return checks, model

    prefix = root / adapter.NODE_PREFIX
    if not prefix.exists():
        checks[CheckKind.INSTALLED] = _check(
            CheckKind.INSTALLED,
            CheckStatus.FAILED,
            "installation-missing",
            "The managed promptfoo installation is missing.",
        )
    elif not adapter._has_path_ownership(record, prefix):
        checks[CheckKind.INSTALLED] = _check(
            CheckKind.INSTALLED,
            CheckStatus.BLOCKED,
            "installation-unowned",
            "The existing installation has no ownership receipt; it will not be executed.",
        )
    elif not adapter._installed_release(prefix):
        checks[CheckKind.INSTALLED] = _check(
            CheckKind.INSTALLED,
            CheckStatus.FAILED,
            "installation-invalid",
            "The installation is incomplete or its pinned package metadata does not match.",
        )
    else:
        checks[CheckKind.INSTALLED] = _check(
            CheckKind.INSTALLED,
            CheckStatus.SUCCEEDED,
            "package-metadata-verified",
            f"Owned promptfoo {adapter.VERSION} metadata and integrity record match; runtime health needs a fresh check.",
            prefix / "node_modules/promptfoo/package.json",
        )

    relative = adapter._filename(options.provider)
    config_path = root / relative
    if not config_path.exists() and not config_path.is_symlink():
        checks[CheckKind.CONFIGURED] = _check(
            CheckKind.CONFIGURED,
            CheckStatus.FAILED,
            "configuration-missing",
            "The selected owned evaluation configuration is missing.",
        )
    elif not any(
        patch.tool_id == "promptfoo" and patch.relative_path == relative
        for step in record.steps
        for patch in step.configuration_ownership
    ):
        checks[CheckKind.CONFIGURED] = _check(
            CheckKind.CONFIGURED,
            CheckStatus.BLOCKED,
            "configuration-unowned",
            "The selected configuration has no ownership receipt; it will not be executed.",
        )
    else:
        try:
            adapter._check_existing_configuration(root, record, relative)
            config = adapter._read_json(config_path)
            model = _model_from_config(config, options)
            if config != adapter._configuration(options.provider, model):
                raise adapter.PromptfooError(
                    "The selected configuration is not the supported two-case profile."
                )
            checks[CheckKind.CONFIGURED] = _check(
                CheckKind.CONFIGURED,
                CheckStatus.SUCCEEDED,
                "owned-configuration-verified",
                "The owned configuration bytes, permissions, and selected evaluation profile match.",
                config_path,
            )
        except (adapter.PromptfooError, OSError, ValueError):
            checks[CheckKind.CONFIGURED] = _check(
                CheckKind.CONFIGURED,
                CheckStatus.FAILED,
                "configuration-invalid",
                "The owned configuration changed, is unsafe, or no longer matches the supported profile.",
            )
    return checks, model


def _prerequisites_ok(checks) -> bool:
    return all(
        checks[kind].status == CheckStatus.SUCCEEDED
        for kind in (CheckKind.INSTALLED, CheckKind.CONFIGURED)
    )


def _block_execution(checks, message: str, code: str = "setup-required") -> None:
    checks[CheckKind.FUNCTIONAL] = _check(CheckKind.FUNCTIONAL, CheckStatus.BLOCKED, code, message)
    if checks[CheckKind.CONNECTED].status != CheckStatus.NOT_APPLICABLE:
        checks[CheckKind.CONNECTED] = _check(
            CheckKind.CONNECTED, CheckStatus.BLOCKED, code, message
        )


def _finish(checks, options) -> ToolVerification:
    return ToolVerification(
        tool_id="promptfoo",
        connection_scope="standalone" if options.provider == "deterministic" else "provider",
        checks=tuple(checks[kind] for kind in CheckKind),
    )


def check_promptfoo(
    root: Path,
    options: VerificationOptions,
    *,
    command_runner: adapter.CommandRunner | None = None,
) -> ToolVerification:
    checks, model = _inspect(root, options)
    if not _prerequisites_ok(checks):
        _block_execution(checks, "Repair or onboard the selected setup before a functional check.")
        return _finish(checks, options)
    if not options.run_functional:
        return _finish(checks, options)
    if options.provider == "openai":
        if not options.allow_provider_usage:
            _block_execution(
                checks,
                "OpenAI checks require --allow-provider-usage and may incur charges.",
                "provider-opt-in-required",
            )
            return _finish(checks, options)
        if not os.environ.get("OPENAI_API_KEY"):
            _block_execution(
                checks, "OPENAI_API_KEY is required for this provider check.", "credential-missing"
            )
            return _finish(checks, options)
    try:
        plan = adapter.plan_promptfoo(
            root, provider=options.provider, model=model, scenario=options.scenario
        )
        outcome = adapter.evaluate_existing_promptfoo(
            plan,
            allow_provider_usage=options.allow_provider_usage,
            command_runner=command_runner,
        )
    except (adapter.PromptfooError, ConfigurationError, OSError, ValidationError):
        checks, _ = _inspect(root, options)
        _block_execution(
            checks,
            "The setup changed or cannot be checked; inspect its receipts and configuration.",
            "check-input-changed",
        )
        return _finish(checks, options)
    # Do not leave old metadata/configuration successes after an observed change.
    checks, _ = _inspect(root, options)
    if not _prerequisites_ok(checks):
        _block_execution(
            checks, "Project setup changed during verification.", "check-input-changed"
        )
        return _finish(checks, options)
    evaluation = outcome.evaluation
    if outcome.status == "blocked":
        _block_execution(checks, outcome.message, "execution-blocked")
        return _finish(checks, options)
    evidence = Path(evaluation.result_path) if evaluation is not None else None
    if evaluation is not None:
        try:
            expected_path = root / adapter.STATE_PREFIX / "results" / f"{plan.run_id}.json"
            if (
                evidence != expected_path
                or adapter._summary(evidence, plan, evaluation.process_returncode) != evaluation
            ):
                raise adapter.PromptfooError("Evaluation evidence does not match this check.")
        except (OSError, ValueError, KeyError, TypeError):
            checks[CheckKind.FUNCTIONAL] = _check(
                CheckKind.FUNCTIONAL,
                CheckStatus.FAILED,
                "evaluation-evidence-invalid",
                "The fresh evaluation evidence is missing, changed, or belongs to another check.",
            )
            if options.provider == "openai":
                checks[CheckKind.CONNECTED] = _check(
                    CheckKind.CONNECTED,
                    CheckStatus.BLOCKED,
                    "evaluation-evidence-invalid",
                    "No valid fresh provider evidence is available.",
                )
            return _finish(checks, options)
    fresh_success = (
        outcome.status == "succeeded"
        and evaluation is not None
        and evaluation.process_returncode == 0
        and evaluation.successes == 2
        and evaluation.failures == evaluation.errors == 0
        and options.scenario == "pass"
    )
    checks[CheckKind.FUNCTIONAL] = _check(
        CheckKind.FUNCTIONAL,
        CheckStatus.SUCCEEDED if fresh_success else CheckStatus.FAILED,
        "fresh-evaluation-passed" if fresh_success else "fresh-evaluation-failed",
        "Both known-result cases passed in this check; this is not a measure of LLM quality."
        if fresh_success
        else (
            "No fresh evaluation was returned by this check."
            if outcome.status == "succeeded"
            else outcome.message
        ),
        evidence,
    )
    if options.provider == "openai":
        responded = False
        if (
            evaluation is not None
            and evaluation.errors == 0
            and (fresh_success or evaluation.process_returncode == 100)
        ):
            try:
                rows = adapter._read_json(Path(evaluation.result_path))["results"]["results"]
                responded = len(rows) == 2 and all(
                    isinstance(row.get("response"), dict)
                    and isinstance(row["response"].get("output"), str)
                    for row in rows
                )
            except (OSError, ValueError, KeyError, TypeError):
                pass
        checks[CheckKind.CONNECTED] = _check(
            CheckKind.CONNECTED,
            CheckStatus.SUCCEEDED if responded else CheckStatus.FAILED,
            "provider-responded" if responded else "provider-response-unverified",
            "The configured OpenAI provider returned both responses; no assistant connection is claimed."
            if responded
            else "This run did not establish a usable response from the configured provider.",
            evidence,
        )
    return _finish(checks, options)

"""Tool-specific observations; setup eligibility is not functional evidence."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, StrictBool, model_validator

from stackwinnow.contracts import Contract, EvidenceRef, Identifier, NonEmptyText, UntrimmedText


class CheckKind(StrEnum):
    INSTALLED = "installed"
    CONFIGURED = "configured"
    CONNECTED = "connected"
    FUNCTIONAL = "functional"


class CheckStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    NOT_RUN = "not_run"
    NOT_APPLICABLE = "not_applicable"


class VerificationCheck(Contract):
    kind: CheckKind
    status: CheckStatus
    code: Identifier
    message: NonEmptyText
    evidence: tuple[EvidenceRef, ...] = ()

    @model_validator(mode="after")
    def applicable_checks(self) -> VerificationCheck:
        if self.status == CheckStatus.NOT_APPLICABLE and self.kind != CheckKind.CONNECTED:
            raise ValueError("Only a connection check can be not applicable.")
        if self.status == CheckStatus.SUCCEEDED and not self.evidence:
            raise ValueError("A successful check requires evidence.")
        return self


def _status(statuses: list[CheckStatus]) -> CheckStatus:
    # Failure or missing evidence must not disappear behind another passing check.
    for status in (CheckStatus.FAILED, CheckStatus.BLOCKED, CheckStatus.NOT_RUN):
        if status in statuses:
            return status
    return CheckStatus.SUCCEEDED


class ToolVerification(Contract):
    tool_id: Identifier
    connection_scope: Literal["standalone", "provider", "assistant", "unknown"]
    checks: tuple[VerificationCheck, ...]

    @model_validator(mode="after")
    def complete_dimensions(self) -> ToolVerification:
        kinds = [item.kind for item in self.checks]
        if len(kinds) != len(CheckKind) or set(kinds) != set(CheckKind):
            raise ValueError("A tool report needs each verification dimension exactly once.")
        connection = next(item for item in self.checks if item.kind == CheckKind.CONNECTED)
        if (connection.status == CheckStatus.NOT_APPLICABLE) != (
            self.connection_scope == "standalone"
        ):
            raise ValueError("Only a standalone tool can omit a connection check.")
        return self

    @property
    def status(self) -> CheckStatus:
        return _status([item.status for item in self.checks])

    @property
    def ready(self) -> bool:
        return self.status == CheckStatus.SUCCEEDED


class VerificationReport(Contract):
    schema_version: Literal[1] = 1
    project_root: UntrimmedText
    checked_at: NonEmptyText
    run_functional: StrictBool
    tools: tuple[ToolVerification, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_tools(self) -> VerificationReport:
        if len({item.tool_id for item in self.tools}) != len(self.tools):
            raise ValueError("Tool verification reports must be unique.")
        if not self.run_functional and any(
            check.kind == CheckKind.FUNCTIONAL and check.status == CheckStatus.SUCCEEDED
            for tool in self.tools
            for check in tool.checks
        ):
            raise ValueError("A fresh functional success requires an executed check.")
        return self

    @property
    def status(self) -> CheckStatus:
        return _status([item.status for item in self.tools])

    @property
    def ready(self) -> bool:
        return self.status == CheckStatus.SUCCEEDED

    def as_payload(self) -> dict:
        """JSON view with derived status/readiness, not caller-supplied verdicts."""
        value = self.model_dump(mode="json")
        value.update(status=self.status.value, ready=self.ready)
        for item, tool in zip(value["tools"], self.tools, strict=True):
            item.update(status=tool.status.value, ready=tool.ready)
        return value


class VerificationOptions(Contract):
    tool_ids: tuple[Identifier, ...] = Field(min_length=1)
    run_functional: StrictBool = False
    provider: Literal["deterministic", "openai"] = "deterministic"
    scenario: Literal["pass", "fail"] = "pass"
    allow_provider_usage: StrictBool = False

    @model_validator(mode="after")
    def validate_options(self) -> VerificationOptions:
        if len(set(self.tool_ids)) != len(self.tool_ids):
            raise ValueError("Select each tool only once.")
        if self.scenario == "fail" and (
            not self.run_functional or self.provider != "deterministic"
        ):
            raise ValueError("The negative control requires a fresh deterministic evaluation.")
        if self.provider != "deterministic" and "promptfoo" not in self.tool_ids:
            raise ValueError("Provider selection currently applies only to promptfoo.")
        return self

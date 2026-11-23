"""Executable modes; catalog membership alone never grants execution support."""

from typing import Literal

from pydantic import Field, model_validator

from stackwinnow.adapters import graphify, headroom, playwright_mcp, promptfoo
from stackwinnow.contracts import Contract


class SupportedMode(Contract):
    tool_id: str
    mode: str
    version: str
    description: str
    requirements: tuple[str, ...]
    provider_usage: Literal[False] = False


def supported_modes() -> tuple[SupportedMode, ...]:
    """Derive pinned releases from the authoritative adapter recipes."""
    host = ("macOS arm64",)
    return (
        SupportedMode(
            tool_id="headroom",
            mode="library",
            version=headroom.VERSION,
            description="Compress a fixed local fixture and measure token counts.",
            requirements=host + ("manager Python >=3.11",),
        ),
        SupportedMode(
            tool_id="promptfoo",
            mode="deterministic",
            version=promptfoo.VERSION,
            description="Run two deterministic local evaluation cases without API keys.",
            requirements=host + ("Node 24", "npm"),
        ),
        SupportedMode(
            tool_id="playwright-mcp",
            mode="codex",
            version=playwright_mcp.VERSION,
            description="Verify browser automation through project Codex settings.",
            requirements=host + ("Node 24", "npm", "Codex " + playwright_mcp.CODEX_VERSION),
        ),
        SupportedMode(
            tool_id="graphify",
            mode="codex",
            version=graphify.VERSION,
            description="Index source code and verify an explicit relationship through Codex.",
            requirements=(
                "macOS >=14 arm64",
                "CPython >=3.11.5,<3.12",
                "Codex " + playwright_mcp.CODEX_VERSION,
            ),
        ),
    )


class ToolSelection(Contract):
    tool_id: str = Field(min_length=1)
    mode: str = Field(min_length=1)
    version: str = Field(min_length=1)

    @model_validator(mode="after")
    def supported(self):
        if not any(
            (self.tool_id, self.mode, self.version) == (m.tool_id, m.mode, m.version)
            for m in supported_modes()
        ):
            raise ValueError(
                "Unsupported tool/mode/version; use 'workflow modes' for executable selections."
            )
        return self


def select_tool(tool_id: str) -> ToolSelection:
    """CLI convenience resolves a tool ID to the one supported pinned mode."""
    for mode in supported_modes():
        if mode.tool_id == tool_id:
            return ToolSelection(tool_id=tool_id, mode=mode.mode, version=mode.version)
    raise ValueError(f"Tool '{tool_id}' has no supported workflow mode; use 'workflow modes'.")

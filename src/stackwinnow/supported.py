"""Executable modes; catalog membership alone never grants execution support."""

from collections.abc import Sequence
from typing import Literal

from packaging.specifiers import SpecifierSet
from packaging.version import Version
from pydantic import Field, model_validator

from stackwinnow.adapters import graphify, headroom, playwright_mcp, promptfoo
from stackwinnow.adapters import langfuse as langfuse_adapter
from stackwinnow.adapters import opik as opik_adapter
from stackwinnow.adapters import ragas as ragas_adapter
from stackwinnow.adapters import trulens as trulens_adapter
from stackwinnow.adapters import deepeval as deepeval_adapter
from stackwinnow.adapters import inspect_ai as inspect_ai_adapter
from stackwinnow.adapters import openlit as openlit_adapter
from stackwinnow.adapters import langchain as langchain_adapter
from stackwinnow.adapters import litellm as litellm_adapter
from stackwinnow.adapters import llmlingua as llmlingua_adapter
from stackwinnow.adapters import gptcache as gptcache_adapter
from stackwinnow.adapters import dspy as dspy_adapter
from stackwinnow.adapters import llama_index as llama_index_adapter
from stackwinnow.adapters import pydantic_ai as pydantic_ai_adapter
from stackwinnow.adapters import haystack as haystack_adapter
from stackwinnow.adapters import langgraph as langgraph_adapter
from stackwinnow.adapters import crewai as crewai_adapter
from stackwinnow.adapters import autogen as autogen_adapter
from stackwinnow.adapters import smolagents as smolagents_adapter
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
        SupportedMode(
            tool_id="opik",
            mode="library",
            version=opik_adapter.VERSION,
            description="Install opik and verify the library import works locally.",
            requirements=host + ("manager Python >=3.10",),
        ),
        SupportedMode(
            tool_id="langfuse",
            mode="library",
            version=langfuse_adapter.VERSION,
            description="Install langfuse and verify the library import works locally.",
            requirements=host + ("manager Python >=3.11",),
        ),
        SupportedMode(
            tool_id="ragas",
            mode="library",
            version=ragas_adapter.VERSION,
            description="Install ragas and verify the library import works locally.",
            requirements=host + ("manager Python >=3.9",),
        ),
        SupportedMode(
            tool_id="trulens",
            mode="library",
            version=trulens_adapter.VERSION,
            description="Install trulens and verify the library import works locally.",
            requirements=host + ("manager Python >=3.10",),
        ),
        SupportedMode(
            tool_id="deepeval",
            mode="library",
            version=deepeval_adapter.VERSION,
            description="Install deepeval and verify the library import works locally.",
            requirements=host + ("manager Python >=3.10",),
        ),
        SupportedMode(
            tool_id="inspect-ai",
            mode="library",
            version=inspect_ai_adapter.VERSION,
            description="Install inspect-ai and verify the library import works locally.",
            requirements=host + ("manager Python >=3.10",),
        ),
        SupportedMode(
            tool_id="openlit",
            mode="library",
            version=openlit_adapter.VERSION,
            description="Install openlit and verify the library import works locally.",
            requirements=host + ("manager Python >=3.10",),
        ),
        SupportedMode(
            tool_id="langchain",
            mode="library",
            version=langchain_adapter.VERSION,
            description="Install langchain and verify the library import works locally.",
            requirements=host + ("manager Python >=3.10",),
        ),
        SupportedMode(
            tool_id="litellm",
            mode="library",
            version=litellm_adapter.VERSION,
            description="Install litellm and verify the library import works locally.",
            requirements=host + ("manager Python >=3.10",),
        ),
        SupportedMode(
            tool_id="llmlingua",
            mode="library",
            version=llmlingua_adapter.VERSION,
            description="Install llmlingua and verify the library import works locally.",
            requirements=host + ("manager Python >=3.10",),
        ),
        SupportedMode(
            tool_id="gptcache",
            mode="library",
            version=gptcache_adapter.VERSION,
            description="Install gptcache and verify the library import works locally.",
            requirements=host + ("manager Python >=3.10",),
        ),
        SupportedMode(
            tool_id="dspy",
            mode="library",
            version=dspy_adapter.VERSION,
            description="Install dspy and verify the library import works locally.",
            requirements=host + ("manager Python >=3.10",),
        ),
        SupportedMode(
            tool_id="llama-index",
            mode="library",
            version=llama_index_adapter.VERSION,
            description="Install llama-index and verify the library import works locally.",
            requirements=host + ("manager Python >=3.10",),
        ),
        SupportedMode(
            tool_id="pydantic-ai",
            mode="library",
            version=pydantic_ai_adapter.VERSION,
            description="Install pydantic-ai and verify the library import works locally.",
            requirements=host + ("manager Python >=3.10",),
        ),
        SupportedMode(
            tool_id="haystack",
            mode="library",
            version=haystack_adapter.VERSION,
            description="Install haystack and verify the library import works locally.",
            requirements=host + ("manager Python >=3.10",),
        ),
        SupportedMode(
            tool_id="langgraph",
            mode="library",
            version=langgraph_adapter.VERSION,
            description="Install langgraph and verify the library import works locally.",
            requirements=host + ("manager Python >=3.10",),
        ),
        SupportedMode(
            tool_id="crewai",
            mode="library",
            version=crewai_adapter.VERSION,
            description="Install crewai and verify the library import works locally.",
            requirements=host + ("manager Python >=3.10",),
        ),
        SupportedMode(
            tool_id="autogen",
            mode="library",
            version=autogen_adapter.VERSION,
            description="Install autogen and verify the library import works locally.",
            requirements=host + ("manager Python >=3.10",),
        ),
        SupportedMode(
            tool_id="smolagents",
            mode="library",
            version=smolagents_adapter.VERSION,
            description="Install smolagents and verify the library import works locally.",
            requirements=host + ("manager Python >=3.10",),
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


def validate_supported_host(tool_ids: Sequence[str], host: tuple[str, str, str, str, str]) -> None:
    """Check observable host requirements without executing prerequisite commands."""
    system, machine, implementation, python_version, macos = host
    if system != "Darwin" or machine != "arm64":
        raise ValueError("The supported workflow modes require macOS arm64.")
    if "graphify" in tool_ids and (
        implementation != "CPython"
        or not SpecifierSet(">=3.11.5,<3.12").contains(python_version)
        or not macos
        or Version(macos) < Version("14")
    ):
        raise ValueError("Graphify requires CPython >=3.11.5,<3.12 on macOS >=14 arm64.")

"""Deterministic tool discovery from declared dependencies and explicit goals."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from stackwinnow.catalog import (
    Catalog,
    Category,
    Eligibility,
    EligibilityContext,
    Platform,
    evaluate_eligibility,
    load_catalog,
)
from stackwinnow.contracts import Contract, Identifier, NonEmptyText
from stackwinnow.detect import InspectionResult


class RecommendationError(ValueError):
    """Explicit selections do not exist in the supplied catalog."""


class MatchReason(Contract):
    kind: Literal["selection", "dependency", "goal"]
    rule_id: Identifier
    message: NonEmptyText
    goals: list[NonEmptyText] = Field(default_factory=list)
    fact_key: str | None = None
    values: list[str] = Field(default_factory=list)
    matched_capabilities: list[NonEmptyText] = Field(default_factory=list)


class ToolRecommendation(Contract):
    tool_id: Identifier
    name: NonEmptyText
    description: NonEmptyText
    category: Category
    selected: bool
    already_declared: bool
    reasons: list[MatchReason] = Field(min_length=1)
    alternatives: list[Identifier]
    conflicts_with: list[Identifier]
    eligibility: Eligibility
    limitations: list[NonEmptyText]


class ToolRelationship(Contract):
    kind: Literal["alternative", "conflict"]
    tools: tuple[Identifier, Identifier]


class RecommendationResult(Contract):
    schema_version: Literal[1] = 1
    rules_version: Literal[1] = 1
    inspection: InspectionResult
    target_platform: Platform | None = None
    recommendations: list[ToolRecommendation]
    relationships: list[ToolRelationship]
    unmatched_goals: list[NonEmptyText]
    model_preference_status: Literal["not-requested", "unrestricted", "unverified"]
    notes: list[NonEmptyText]

    @property
    def complete(self) -> bool:
        """Inspection completeness, independent of matching and setup eligibility."""
        return self.inspection.complete


@dataclass(frozen=True)
class _GoalRule:
    rule_id: str
    phrases: tuple[str, ...]
    capabilities: frozenset[str]
    explanation: str


_RULES = (
    _GoalRule(
        "code-navigation",
        (
            "code navigation",
            "navigate code",
            "understand codebase",
            "understand the codebase",
            "code relationships",
            "relationships across source files",
            "code indexing",
            "refactoring",
        ),
        frozenset({"code-navigation", "symbol-search", "code-relationships"}),
        "Provides code navigation or relationship discovery for the requested goal.",
    ),
    _GoalRule(
        "evaluation",
        (
            "evaluation",
            "evaluate answers",
            "evaluate prompts",
            "evaluate models",
            "evaluate outputs",
            "evaluate model outputs",
            "model comparison",
            "prompt testing",
        ),
        frozenset({"prompt-evaluation", "llm-evaluation", "model-evaluation", "agent-evaluation"}),
        "Provides evaluation capabilities for the requested goal.",
    ),
    _GoalRule(
        "retrieval-evaluation",
        ("rag evaluation", "evaluate retrieval", "evaluate rag"),
        frozenset({"rag-evaluation"}),
        "Provides retrieval evaluation capabilities for the requested goal.",
    ),
    _GoalRule(
        "cost-optimization",
        (
            "reduce cost",
            "reduce costs",
            "lower cost",
            "lower costs",
            "cost optimization",
            "cost optimisation",
        ),
        frozenset(
            {
                "token-optimization",
                "context-compression",
                "response-caching",
                "model-routing",
                "spend-tracking",
            }
        ),
        "Provides compression, caching, routing, or spend measurement; savings require benchmarking.",
    ),
    _GoalRule(
        "context-compression",
        (
            "reduce tokens",
            "reduce token usage",
            "reduce context tokens",
            "token optimization",
            "token optimisation",
            "context compression",
            "compress context",
            "prompt compression",
            "compress prompts",
        ),
        frozenset({"token-optimization", "context-compression", "prompt-compression"}),
        "Provides context or prompt compression; quality and token savings require benchmarking.",
    ),
    _GoalRule(
        "response-caching",
        ("reduce model calls", "response caching", "cache responses", "semantic caching"),
        frozenset({"response-caching", "semantic-caching"}),
        "Provides response caching to reuse prior outputs; correctness and savings require benchmarking.",
    ),
    _GoalRule(
        "spend-monitoring",
        ("track costs", "track spending", "monitor costs", "monitor spend", "spend tracking"),
        frozenset({"spend-tracking"}),
        "Provides spend measurement; observing costs does not itself reduce them.",
    ),
    _GoalRule(
        "model-routing",
        ("model routing", "route models", "provider gateway"),
        frozenset({"model-routing", "provider-gateway"}),
        "Provides model routing or a provider gateway; savings depend on routing policy and workload.",
    ),
    _GoalRule(
        "agent-workflows",
        ("agent orchestration", "agent workflows", "multi agent", "build agents"),
        frozenset({"agent-orchestration", "typed-agents", "code-agents"}),
        "Provides agent workflow capabilities; consider declared frameworks before adding another.",
    ),
)

# Distribution/package names are exact aliases, not substring matches or installed-state checks.
_PYTHON_PACKAGES = {
    "graphifyy": "graphify",
    "gptcache": "gptcache",
    "deepeval": "deepeval",
    "dspy": "dspy",
    "dspy-ai": "dspy",
    "inspect-ai": "inspect-ai",
    "langchain": "langchain",
    "langchain-core": "langchain",
    "langgraph": "langgraph",
    "llama-index": "llama-index",
    "llama-index-core": "llama-index",
    "haystack-ai": "haystack",
    "pydantic-ai": "pydantic-ai",
    "pydantic-ai-slim": "pydantic-ai",
    "crewai": "crewai",
    "autogen-agentchat": "autogen",
    "smolagents": "smolagents",
    "ragas": "ragas",
    "trulens": "trulens",
    "litellm": "litellm",
    "llmlingua": "llmlingua",
    "langfuse": "langfuse",
    "openlit": "openlit",
    "opik": "opik",
}
_NODE_PACKAGES = {
    "promptfoo": "promptfoo",
    "@playwright/mcp": "playwright-mcp",
    "langfuse": "langfuse",
}
_NODE_FACTS = frozenset(
    {
        "node.dependencies",
        "node.devDependencies",
        "node.optionalDependencies",
        "node.peerDependencies",
    }
)


def _goal_text(goal: str) -> str:
    normalized = (
        unicodedata.normalize("NFKC", goal)
        .casefold()
        .translate(str.maketrans({"’": "'", "‘": "'", "ʼ": "'"}))
    )
    words = re.findall(r"[a-z0-9]+(?:['-][a-z0-9]+)*", normalized)
    parts = {part for word in words for part in word.split("-")}
    # This small phrase matcher cannot safely interpret negated/conditional prose.
    if {"no", "not", "never", "avoid", "without", "unless", "if", "cannot"} & parts or any(
        part.endswith("n't") for part in parts
    ):
        return ""
    return " " + " ".join(words) + " "


def recommend_tools(
    inspection: InspectionResult,
    *,
    catalog: Catalog | None = None,
    platform: Platform | None = None,
) -> RecommendationResult:
    """Explain matches without executing tools, inspecting the host, or changing selections."""
    catalog = catalog if catalog is not None else load_catalog()
    inspection = InspectionResult.model_validate_json(inspection.model_dump_json())
    selected = list(dict.fromkeys(inspection.selected_tools))
    selected_order = {tool_id: index for index, tool_id in enumerate(selected)}
    by_id = {tool.tool_id: tool for tool in catalog.tools}
    if any(tool_id not in by_id for tool_id in selected):
        raise RecommendationError("Selected tool ID is absent from the recommendation catalog.")
    reasons: dict[str, list[MatchReason]] = {}
    for tool_id in selected:
        reasons[tool_id] = [
            MatchReason(
                kind="selection",
                rule_id="explicit-selection",
                message="Explicitly selected by the user; retained regardless of automatic matches.",
            )
        ]
    for key, values in sorted(inspection.profile.facts.items()):
        if key == "python.dependencies" or key.startswith("python.optional_dependencies."):
            aliases = _PYTHON_PACKAGES
        elif key in _NODE_FACTS:
            aliases = _NODE_PACKAGES
        else:
            continue
        found: dict[str, list[str]] = {}
        for value in sorted(set(values)):
            tool_id = aliases.get(value)
            if tool_id in by_id:
                found.setdefault(tool_id, []).append(value)
        for tool_id, names in found.items():
            reasons.setdefault(tool_id, []).append(
                MatchReason(
                    kind="dependency",
                    rule_id="declared-dependency",
                    fact_key=key,
                    values=names,
                    message="Declared in project dependencies; reuse may avoid introducing another tool. "
                    "This does not prove installation or use at runtime.",
                )
            )
    goals = {goal: _goal_text(goal) for goal in dict.fromkeys(inspection.profile.goals)}
    matched_goals: set[str] = set()
    for rule in _RULES:
        # Hyphens may join phrase words, but must not expose words inside compounds.
        phrases = [
            re.compile(" " + "[ -]".join(re.escape(word) for word in phrase.split()) + " ")
            for phrase in rule.phrases
        ]
        matches = sorted(
            goal
            for goal, normalized in goals.items()
            if any(phrase.search(normalized) for phrase in phrases)
        )
        if not matches:
            continue
        for tool in catalog.tools:
            capabilities = sorted(rule.capabilities.intersection(tool.capabilities))
            if capabilities:
                reasons.setdefault(tool.tool_id, []).append(
                    MatchReason(
                        kind="goal",
                        rule_id=rule.rule_id,
                        message=rule.explanation,
                        goals=matches,
                        matched_capabilities=capabilities,
                    )
                )
                matched_goals.update(matches)
    context = EligibilityContext.from_profile(inspection.profile)
    context = EligibilityContext.model_validate(
        {
            **context.model_dump(),
            "platform": platform if platform is not None else context.platform,
            "selected_tools": selected,
        }
    )
    recommendations = []
    for tool_id, matches in reasons.items():
        tool = by_id[tool_id]
        recommendations.append(
            ToolRecommendation(
                tool_id=tool_id,
                name=tool.name,
                description=tool.description,
                category=tool.category,
                selected=tool_id in selected_order,
                already_declared=any(reason.kind == "dependency" for reason in matches),
                reasons=matches,
                alternatives=sorted(tool.alternatives),
                conflicts_with=sorted(set(tool.conflicts) & reasons.keys()),
                eligibility=evaluate_eligibility(tool, context),
                limitations=tool.limitations,
            )
        )

    def order(item: ToolRecommendation) -> tuple[int, int, str]:
        if item.selected:
            return 0, selected_order[item.tool_id], item.tool_id
        return (
            1 if item.already_declared else 2,
            -sum(reason.kind == "goal" for reason in item.reasons),
            item.tool_id,
        )

    recommendations.sort(key=order)
    relationships: set[tuple[str, tuple[str, str]]] = set()
    for item in recommendations:
        for kind, related in (
            ("alternative", item.alternatives),
            ("conflict", item.conflicts_with),
        ):
            for other in related:
                if other in reasons:
                    relationships.add((kind, tuple(sorted((item.tool_id, other)))))
    preference = inspection.model_preference
    preference_status = (
        "not-requested"
        if preference is None
        else ("unrestricted" if preference == "any" else "unverified")
    )
    notes = [
        "Matches describe potential fit. No installation or runtime prerequisites were checked."
    ]
    if not inspection.complete:
        notes.append(
            "Inspection is incomplete; recommendations use only the valid findings available."
        )
    if preference_status == "unverified":
        notes.append(
            f"The {preference} model preference is recorded, but the catalog does not verify "
            "model/backend support per tool. Confirm it before choosing a setup."
        )
    if not recommendations:
        notes.append(
            "No tools matched. Supply a supported goal or explicitly select a catalog tool."
        )
    unmatched = [goal for goal in goals if goal not in matched_goals]
    if unmatched:
        notes.append(
            "Some goals were not matched. Rules recognize documented English phrases; "
            "negated or conditional goals require explicit selection or rephrasing."
        )
    return RecommendationResult(
        inspection=inspection,
        target_platform=context.platform,
        recommendations=recommendations,
        relationships=[
            ToolRelationship(kind=kind, tools=pair) for kind, pair in sorted(relationships)
        ],
        unmatched_goals=unmatched,
        model_preference_status=preference_status,
        notes=notes,
    )

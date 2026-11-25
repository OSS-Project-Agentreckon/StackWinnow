# src/stackwinnow/wizard.py
"""Interactive installation wizard — groups, selects, and installs AI tools."""

from __future__ import annotations

from stackwinnow.catalog import Category
from stackwinnow.recommend import ToolRecommendation

_CATEGORY_ORDER = [
    Category.OBSERVABILITY,
    Category.EVALUATION,
    Category.CONTEXT,
    Category.MODEL_GATEWAY,
]

# Used by display functions (_print_category_menu, _print_selection_summary) added in wizard.py.
_CATEGORY_LABELS = {
    Category.OBSERVABILITY: ("OBSERVABILITY", "Trace LLM calls, track spend, monitor AI performance"),
    Category.EVALUATION: ("EVALUATION", "Test prompts, measure output quality, validate responses"),
    Category.CONTEXT: ("CONTEXT COMPRESSION", "Reduce tokens before LLM calls to lower cost and latency"),
    Category.MODEL_GATEWAY: ("MODEL ROUTING", "Route between models, unify API calls, track spend"),
}


def group_by_category(
    recommendations: list[ToolRecommendation],
    library_tool_ids: set[str],
) -> dict[str, list[ToolRecommendation]]:
    """Group recommendations by category, keeping only library-mode tools in display order."""
    buckets: dict[str, list[ToolRecommendation]] = {}
    for rec in recommendations:
        if rec.tool_id not in library_tool_ids:
            continue
        key = rec.category
        buckets.setdefault(key, []).append(rec)
    ordered: dict[str, list[ToolRecommendation]] = {}
    for cat in _CATEGORY_ORDER:
        key = cat
        if key in buckets:
            ordered[key] = buckets.pop(key)
    for key, tools in sorted(buckets.items()):
        ordered[key] = tools
    return ordered


def parse_selection(raw: str, tools: list[ToolRecommendation]) -> list[ToolRecommendation] | None:
    """Parse a category selection string.

    Returns:
        list[ToolRecommendation] — selected tools (empty list for 'skip', all tools for 'all')
        None — if input is invalid or references out-of-range letters
    """
    text = raw.strip().lower()
    if text == "skip":
        return []
    if text == "all":
        return list(tools)
    if not text:
        return None
    letters = [part.strip() for part in text.split(",")]
    seen: set[int] = set()
    selected = []
    max_letter = chr(ord("a") + len(tools) - 1)
    for letter in letters:
        if len(letter) != 1 or letter < "a" or letter > max_letter:
            return None
        index = ord(letter) - ord("a")
        if index not in seen:
            seen.add(index)
            selected.append(tools[index])
    return selected

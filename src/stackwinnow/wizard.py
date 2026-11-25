# src/stackwinnow/wizard.py
"""Interactive installation wizard — groups, selects, and installs AI tools."""

from __future__ import annotations

import sys

from stackwinnow.catalog import Category
from stackwinnow.recommend import ToolRecommendation

_RESET = "\033[0m"
_BOLD = "\033[1m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_CYAN = "\033[36m"
_DIM = "\033[2m"
_DIVIDER = "─" * 50


def _c(code: str, text: str, *, tty: bool) -> str:
    return f"{code}{text}{_RESET}" if tty else text


def _ok(tty: bool) -> str:
    return _c(_GREEN, "✓", tty=tty)


def _fail(tty: bool) -> str:
    return _c(_RED, "✗", tty=tty)


def _print_header(project_root: str, tty: bool) -> None:
    if tty:
        print(_c(_BOLD, "╔══════════════════════════════════════════════════╗", tty=tty))
        print(_c(_BOLD, "║        StackWinnow — Installation Wizard         ║", tty=tty))
        print(_c(_BOLD, "╚══════════════════════════════════════════════════╝", tty=tty))
    else:
        print("StackWinnow — Installation Wizard")
    print(f"\nProject : {project_root}")


def _print_divider(label: str, tty: bool) -> None:
    print(_c(_DIM, _DIVIDER, tty=tty))
    print(_c(_BOLD, f" {label}", tty=tty))
    print(_c(_DIM, _DIVIDER, tty=tty))


def _print_category_menu(
    n: int,
    total: int,
    category_key: str,
    tools: list[ToolRecommendation],
    tty: bool,
) -> None:
    label, desc = _CATEGORY_LABELS.get(
        category_key,
        (category_key.upper().replace("-", " "), ""),
    )
    _print_divider(f"{n} / {total}  {_c(_CYAN, label, tty=tty)}", tty=tty)
    if desc:
        print(f" {_c(_DIM, desc, tty=tty)}")
    print()
    for i, rec in enumerate(tools):
        letter = chr(ord("a") + i)
        print(f"  {_c(_BOLD, letter + ')', tty=tty)} {rec.name:<14} — {rec.description}")
    print()


def _print_selection_summary(
    selections: list[ToolRecommendation],
    groups: dict[str, list[ToolRecommendation]],
    tty: bool,
) -> None:
    _print_divider(f"Your selection ({len(selections)} tools)", tty=tty)
    cat_lookup = {
        rec.tool_id: cat_key
        for cat_key, recs in groups.items()
        for rec in recs
    }
    for rec in selections:
        label, _ = _CATEGORY_LABELS.get(
            cat_lookup.get(rec.tool_id, ""),
            (cat_lookup.get(rec.tool_id, "").upper(), ""),
        )
        print(f"  {_ok(tty)} {rec.name:<14} {label}")
    print()


def _print_step_previews(batch: list[ToolRecommendation], tty: bool) -> None:
    for rec in batch:
        print(f"  {_c(_DIM, rec.name, tty=tty):<20} Installing {rec.name}...")


def _print_round_results(
    batch: list[ToolRecommendation],
    outcomes: list,
    tty: bool,
) -> None:
    outcome_map = {o.phase: o.status for o in outcomes}
    for rec in batch:
        status = outcome_map.get(rec.tool_id, "blocked")
        if status == "succeeded":
            print(f"  {_ok(tty)} {rec.name:<14} installed")
        else:
            msg = next((o.message for o in outcomes if o.phase == rec.tool_id), "failed")
            short = msg.split("\n")[0][:60]
            print(f"  {_fail(tty)} {rec.name:<14} {_c(_DIM, short, tty=tty)}")


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


def split_batches(
    tools: list[ToolRecommendation], batch_size: int = 4
) -> list[list[ToolRecommendation]]:
    """Split tools into ordered batches of at most batch_size."""
    if not tools:
        return []
    return [tools[i : i + batch_size] for i in range(0, len(tools), batch_size)]

"""Recommendations explain project fit without installing or claiming readiness."""

import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from stackwinnow.catalog import Catalog, load_catalog
from stackwinnow.contracts import ProjectProfile
from stackwinnow.detect import InspectionResult, inspect_project
from stackwinnow.recommend import RecommendationError, RecommendationResult, recommend_tools


def profile(*goals: str, **kwargs) -> InspectionResult:
    return InspectionResult(
        profile=ProjectProfile(project_root="/example", goals=list(goals)), **kwargs
    )


def ids(result: RecommendationResult) -> list[str]:
    return [item.tool_id for item in result.recommendations]


def test_navigation_and_evaluation_have_different_explained_matches():
    navigation = recommend_tools(profile("Understand relationships across source files"))
    evaluation = recommend_tools(profile("Evaluate answers"))
    assert set(ids(navigation)) == {"graphify", "serena"}
    assert "promptfoo" in ids(evaluation) and "graphify" not in ids(evaluation)
    assert all(item.reasons[0].goals == ["Evaluate answers"] for item in evaluation.recommendations)
    assert not navigation.unmatched_goals and not evaluation.unmatched_goals


def test_cost_matches_explain_tradeoffs_without_promising_savings():
    result = recommend_tools(profile("Reduce costs"))
    assert {"headroom", "llmlingua", "gptcache", "litellm"} <= set(ids(result))
    assert all("benchmarking" in item.reasons[0].message for item in result.recommendations)
    assert all(item.limitations for item in result.recommendations)


@pytest.mark.parametrize(
    "goal,expected",
    [
        ("Compress context", {"headroom", "llmlingua"}),
        ("Reduce context tokens", {"headroom", "llmlingua"}),
        ("Reduce model calls", {"gptcache"}),
        ("Cache responses", {"gptcache"}),
        ("Track costs", {"langfuse", "litellm", "openlit"}),
        ("Model routing", {"litellm"}),
    ],
)
def test_specific_cost_goals_match_only_relevant_capabilities(goal, expected):
    result = recommend_tools(profile(goal))
    assert set(ids(result)) == expected
    assert not result.unmatched_goals


def test_explicit_choice_survives_narrower_goal_rules():
    result = recommend_tools(profile("Compress context", selected_tools=["langfuse"]))
    assert ids(result) == ["langfuse", "headroom", "llmlingua"]
    assert [reason.kind for reason in result.recommendations[0].reasons] == ["selection"]


def test_goal_reasons_identify_exact_matching_capabilities():
    result = recommend_tools(profile("Compress context", "Track costs"))
    tools = {item.tool_id: item for item in result.recommendations}
    assert tools["headroom"].reasons[0].matched_capabilities == [
        "context-compression",
        "token-optimization",
    ]
    assert tools["langfuse"].reasons[0].matched_capabilities == ["spend-tracking"]
    assert tools["headroom"].reasons[0].goals == ["Compress context"]
    assert tools["langfuse"].reasons[0].goals == ["Track costs"]


def test_empty_project_does_not_invent_a_need_for_tools(tmp_path):
    result = recommend_tools(inspect_project(tmp_path))
    assert result.complete and not result.recommendations
    assert any("No tools matched" in note for note in result.notes)


@pytest.mark.parametrize(
    "goal",
    [
        "deploy a database",
        "do not evaluate answers",
        "avoid code navigation",
        "evaluate answers without hosted models",
        "reevaluation",
        "re-evaluation of model outputs",
        "non-evaluation",
        "evaluation-driven",
        "not-evaluation but code navigation",
        "Don’t-evaluate answers but code navigation",
        "if evaluation helps",
        "Don't evaluate answers",
        "Don’t evaluate answers",
        "Don‘t evaluate answers",
        "Donʼt evaluate answers",
        "Don＇t evaluate answers",
        "I won't evaluate answers",
        "I wouldn’t evaluate answers",
        "I can't evaluate answers",
        "I cannot evaluate answers",
        "We shouldn’t use code navigation",
    ],
)
def test_unrecognized_negated_or_conditional_goals_are_explicitly_unmatched(goal):
    result = recommend_tools(profile(goal))
    assert result.unmatched_goals == [goal]
    assert not result.recommendations


def test_matching_is_case_and_separator_insensitive_and_not_double_counted():
    result = recommend_tools(profile("CODE-NAVIGATION", "CODE-NAVIGATION", "code navigation"))
    assert set(ids(result)) == {"graphify", "serena"}
    assert all(len(item.reasons) == 1 for item in result.recommendations)
    assert result.recommendations[0].reasons[0].goals == ["CODE-NAVIGATION", "code navigation"]


def test_positive_goal_with_apostrophe_still_matches():
    assert set(ids(recommend_tools(profile("We’d like code navigation")))) == {"graphify", "serena"}


@pytest.mark.parametrize("goal", ["cost-optimization", "multi-agent", "reduce context-tokens"])
def test_supported_hyphenated_phrases_match_like_spaces(goal):
    result = recommend_tools(profile(goal))
    assert not result.unmatched_goals
    assert ids(result) == ids(recommend_tools(profile(goal.replace("-", " "))))


def test_manual_choices_are_retained_in_selection_order_despite_unmatched_goal():
    source = profile("deploy a database", selected_tools=["promptfoo", "graphify", "promptfoo"])
    before = source.model_dump_json()
    result = recommend_tools(source)
    assert ids(result) == ["promptfoo", "graphify"]
    assert all(item.selected for item in result.recommendations)
    assert result.unmatched_goals == ["deploy a database"]
    assert source.model_dump_json() == before


def test_existing_framework_ranks_above_alternatives_and_keeps_evidence(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies=["langgraph>=0.2"]')
    result = recommend_tools(inspect_project(tmp_path, goals=["Build agent workflows"]))
    assert ids(result)[0] == "langgraph"
    first = result.recommendations[0]
    assert first.already_declared and not first.selected
    assert first.reasons[0].fact_key == "python.dependencies"
    assert first.reasons[0].values == ["langgraph"]
    assert any(e.source == "pyproject.toml" for e in result.inspection.profile.evidence)
    assert any(r.kind == "alternative" and "langgraph" in r.tools for r in result.relationships)


def test_mixed_python_node_and_optional_dependency_aliases(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies=["LangChain_Core>=0.2"]\n'
        '[project.optional-dependencies]\neval=["ragas"]'
    )
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "devDependencies": {"promptfoo": "0.125.1", "@playwright/mcp": "*"},
            }
        )
    )
    result = recommend_tools(inspect_project(tmp_path))
    assert set(ids(result)) == {"langchain", "ragas", "promptfoo", "playwright-mcp"}
    assert all(item.already_declared for item in result.recommendations)
    ragas = next(item for item in result.recommendations if item.tool_id == "ragas")
    assert ragas.reasons[0].fact_key == "python.optional_dependencies.eval"


def test_package_names_do_not_match_substrings_or_registration_labels(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies":{"my-promptfoo-wrapper":"*"}}')
    (tmp_path / "settings.json").write_text('{"mcpServers":{"graphify":{}}}')
    result = recommend_tools(inspect_project(tmp_path, config_path="settings.json"))
    assert not result.recommendations


def test_partial_inspection_preserves_matches_and_failure_diagnostics(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies=["ragas"]')
    (tmp_path / "package.json").write_text('{invalid: "synthetic-secret"}')
    result = recommend_tools(inspect_project(tmp_path, goals=["Evaluate answers"]))
    assert not result.complete and ids(result)[0] == "ragas"
    assert "promptfoo" in ids(result)
    assert any(item.status == "failed" for item in result.inspection.diagnostics)
    assert "synthetic-secret" not in result.model_dump_json()


@pytest.mark.parametrize(
    "preference,expected",
    [
        (None, "not-requested"),
        ("any", "unrestricted"),
        ("local", "unverified"),
        ("hosted", "unverified"),
    ],
)
def test_model_preference_is_preserved_without_fabricating_backend_support(preference, expected):
    result = recommend_tools(
        profile("Evaluate answers", model_preference=preference, selected_tools=["promptfoo"])
    )
    assert result.inspection.model_preference == preference
    assert result.model_preference_status == expected
    assert result.recommendations[0].tool_id == "promptfoo"
    if expected == "unverified":
        assert any("catalog does not verify" in note for note in result.notes)


def conflict_catalog() -> Catalog:
    catalog = load_catalog()
    changes = {"graphify": ["serena"], "serena": ["graphify"]}
    return catalog.model_copy(
        update={
            "tools": tuple(
                entry.model_copy(update={"conflicts": changes[entry.tool_id]})
                if entry.tool_id in changes
                else entry
                for entry in catalog.tools
            )
        }
    )


def test_conflicting_manual_choices_remain_visible_and_block_eligibility():
    result = recommend_tools(
        profile(selected_tools=["graphify", "serena"]), catalog=conflict_catalog()
    )
    assert ids(result) == ["graphify", "serena"]
    assert all(item.selected for item in result.recommendations)
    assert all(
        any(reason.code == "selection-conflict" for reason in item.eligibility.reasons)
        for item in result.recommendations
    )
    conflicts = [r for r in result.relationships if r.kind == "conflict"]
    assert len(conflicts) == 1 and conflicts[0].tools == ("graphify", "serena")


def test_conflicting_suggestions_are_not_treated_as_user_selections():
    result = recommend_tools(profile("code navigation"), catalog=conflict_catalog())
    assert all(item.conflicts_with for item in result.recommendations)
    assert not result.inspection.selected_tools
    assert all(
        not any(reason.code == "selection-conflict" for reason in item.eligibility.reasons)
        for item in result.recommendations
    )


def test_alternatives_are_not_installation_conflicts():
    result = recommend_tools(profile(selected_tools=["graphify", "serena"]))
    assert [r.kind for r in result.relationships] == ["alternative"]
    assert all(not item.conflicts_with for item in result.recommendations)


def test_catalog_only_matches_never_become_ready_from_goal_or_selection():
    result = recommend_tools(
        profile("Evaluate answers", selected_tools=["promptfoo"]), platform="macos"
    )
    assert result.target_platform == "macos"
    assert result.inspection.profile.operating_system is None
    for item in result.recommendations:
        assert not item.eligibility.installable
        assert "adapter-unavailable" in {r.code for r in item.eligibility.reasons}
        assert "prerequisites-unverified" in {r.code for r in item.eligibility.reasons}


def test_unknown_selection_is_rejected_by_api():
    with pytest.raises(RecommendationError, match="Selected tool ID"):
        recommend_tools(profile(selected_tools=["unknown-tool"]))


def test_mutated_selection_is_revalidated_by_api():
    source = profile(selected_tools=["graphify"])
    source.selected_tools.append("invalid tool id")
    with pytest.raises(ValidationError):
        recommend_tools(source)


def test_project_inspection_leaves_target_platform_explicitly_unknown(tmp_path):
    result = recommend_tools(inspect_project(tmp_path, goals=["code navigation"]))
    assert result.target_platform is None
    assert all(
        "platform-unknown" in {reason.code for reason in item.eligibility.reasons}
        for item in result.recommendations
    )


@pytest.mark.parametrize(
    "facts,operating_system,expected",
    [
        ({"os": ["linux"]}, "Darwin Kernel Version 27.0.0", "linux"),
        ({}, "Darwin Kernel Version 27.0.0", "macos"),
    ],
)
def test_profile_platform_evidence_and_explicit_override(facts, operating_system, expected):
    source = InspectionResult(
        profile=ProjectProfile(
            project_root="/example",
            goals=["code navigation"],
            facts=facts,
            operating_system=operating_system,
        ),
        selected_tools=["graphify"],
    )
    before = source.model_dump_json()
    assert recommend_tools(source).target_platform == expected
    override = recommend_tools(source, platform="windows")
    assert override.target_platform == "windows"
    assert override.recommendations[0].selected
    assert source.model_dump_json() == before
    with pytest.raises(ValidationError):
        recommend_tools(source, platform="unsupported-platform")


def test_result_roundtrip_stability_and_no_execution(monkeypatch):
    source = profile("code navigation", selected_tools=["graphify"])
    catalog = load_catalog()
    before = source.model_dump_json(), catalog.model_dump_json()

    def forbidden(*args, **kwargs):
        raise AssertionError("Recommendations must not execute tools or inspect the host")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(Path, "home", forbidden)
    result = recommend_tools(source, catalog=catalog)
    reverse = catalog.model_copy(update={"tools": tuple(reversed(catalog.tools))})
    assert recommend_tools(source, catalog=reverse) == result
    assert RecommendationResult.model_validate_json(result.model_dump_json()) == result
    assert (source.model_dump_json(), catalog.model_dump_json()) == before

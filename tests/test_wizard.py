# tests/test_wizard.py
import pytest
from unittest.mock import MagicMock
from stackwinnow.catalog import Category
from stackwinnow.wizard import group_by_category, parse_selection


def _rec(tool_id, category):
    r = MagicMock()
    r.tool_id = tool_id
    r.category = category
    return r


def test_group_by_category_basic():
    recs = [
        _rec("langfuse", Category.OBSERVABILITY),
        _rec("openlit", Category.OBSERVABILITY),
        _rec("deepeval", Category.EVALUATION),
        _rec("litellm", Category.MODEL_GATEWAY),
    ]
    library_ids = {"langfuse", "openlit", "deepeval", "litellm"}
    groups = group_by_category(recs, library_ids)
    assert list(groups.keys()) == ["observability", "evaluation", "model-gateway"]
    assert [r.tool_id for r in groups["observability"]] == ["langfuse", "openlit"]
    assert [r.tool_id for r in groups["evaluation"]] == ["deepeval"]
    assert [r.tool_id for r in groups["model-gateway"]] == ["litellm"]


def test_group_by_category_excludes_non_library():
    recs = [
        _rec("langfuse", Category.OBSERVABILITY),
        _rec("promptfoo", Category.EVALUATION),  # not in library_ids
    ]
    library_ids = {"langfuse"}
    groups = group_by_category(recs, library_ids)
    assert "observability" in groups
    assert "evaluation" not in groups


def test_group_by_category_display_order():
    recs = [
        _rec("litellm", Category.MODEL_GATEWAY),
        _rec("deepeval", Category.EVALUATION),
        _rec("langfuse", Category.OBSERVABILITY),
        _rec("headroom", Category.CONTEXT),
    ]
    library_ids = {"litellm", "deepeval", "langfuse", "headroom"}
    groups = group_by_category(recs, library_ids)
    assert list(groups.keys()) == [
        "observability", "evaluation", "context", "model-gateway"
    ]


def test_group_by_category_fallback_order():
    recs = [
        _rec("gptcache", Category.CACHING),
        _rec("langfuse", Category.OBSERVABILITY),
    ]
    library_ids = {"gptcache", "langfuse"}
    groups = group_by_category(recs, library_ids)
    keys = list(groups.keys())
    # observability is in _CATEGORY_ORDER; caching falls back to alphabetical after
    assert keys[0] == "observability"
    assert "caching" in keys


def test_group_by_category_empty_recommendations():
    groups = group_by_category([], {"langfuse"})
    assert groups == {}


def test_group_by_category_all_excluded():
    recs = [_rec("langfuse", Category.OBSERVABILITY)]
    groups = group_by_category(recs, set())  # empty library_ids
    assert groups == {}


@pytest.fixture
def sample_tools():
    tools = []
    for tid in ("langfuse", "openlit", "deepeval"):
        m = MagicMock()
        m.tool_id = tid
        tools.append(m)
    return tools


def test_parse_selection_single_letter(sample_tools):
    result = parse_selection("a", sample_tools)
    assert result == [sample_tools[0]]


def test_parse_selection_multiple_letters(sample_tools):
    result = parse_selection("a,c", sample_tools)
    assert result == [sample_tools[0], sample_tools[2]]


def test_parse_selection_all(sample_tools):
    result = parse_selection("all", sample_tools)
    assert result == sample_tools


def test_parse_selection_skip(sample_tools):
    result = parse_selection("skip", sample_tools)
    assert result == []


def test_parse_selection_invalid_letter(sample_tools):
    result = parse_selection("z", sample_tools)
    assert result is None


def test_parse_selection_mixed_valid_invalid(sample_tools):
    result = parse_selection("a,z", sample_tools)
    assert result is None


def test_parse_selection_empty(sample_tools):
    result = parse_selection("", sample_tools)
    assert result is None


def test_parse_selection_duplicate_letters(sample_tools):
    result = parse_selection("a,a", sample_tools)
    assert result == [sample_tools[0]]


def test_parse_selection_whitespace_padded(sample_tools):
    result = parse_selection("  a , c  ", sample_tools)
    assert result == [sample_tools[0], sample_tools[2]]

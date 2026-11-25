# tests/test_wizard.py
from unittest.mock import MagicMock
from stackwinnow.catalog import Category
from stackwinnow.wizard import group_by_category


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

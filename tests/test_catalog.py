"""Catalog gates use synthetic adapter metadata; no integrations run in these tests."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from stackwinnow.catalog import (
    Catalog,
    CatalogEntry,
    CatalogError,
    Category,
    EligibilityContext,
    Platform,
    evaluate_eligibility,
    filter_catalog,
    load_catalog,
)
from stackwinnow.contracts import ProjectProfile


def entry(**changes: object) -> CatalogEntry:
    data = {
        "tool_id": "example-tool",
        "name": "Example",
        "description": "Synthetic test entry.",
        "repository": "https://example.invalid/repo",
        "license": "MIT",
        "license_review": "reviewed",
        "license_scope": "Synthetic fixture, not an upstream license review.",
        "category": "evaluation",
        "availability": "adapter_available",
        "prerequisites": ["Synthetic prerequisite check must pass."],
        "compatibility_notes": "Synthetic macOS/Codex fixture.",
        "supported_platforms": ["macos"],
        "supported_assistants": ["codex"],
        "limitations": ["Not a real adapter."],
        "reviewed_on": "2026-11-16",
        "sources": [
            {"kind": "readme", "url": "https://example.invalid/README", "sha256": "a" * 64},
            {"kind": "license", "url": "https://example.invalid/LICENSE", "sha256": "b" * 64},
        ],
    }
    return CatalogEntry.model_validate({**data, **changes})


def ready_context(**changes: object) -> EligibilityContext:
    return EligibilityContext.model_validate(
        {
            "platform": "macos",
            "assistant": "codex",
            "registered_adapters": ["example-tool"],
            "prerequisite_checks": {"example-tool": "succeeded"},
            **changes,
        }
    )


def codes(tool: CatalogEntry, context: EligibilityContext) -> set[str]:
    result = evaluate_eligibility(tool, context)
    assert not result.installable
    return {reason.code for reason in result.reasons}


def test_bundled_catalog_has_unique_reviewed_entries() -> None:
    catalog = load_catalog()
    assert catalog.tools
    assert len({tool.tool_id for tool in catalog.tools}) == len(catalog.tools)
    for tool in catalog.tools:
        assert tool.license_review == "reviewed"
        assert {source.kind for source in tool.sources} >= {"license", "readme"}
        assert tool.availability in ("catalog_only", "adapter_available")
        if tool.availability == "adapter_available":
            # Every entry that claims an adapter must have a corresponding module.
            import importlib.util

            module_name = f"stackwinnow.adapters.{tool.tool_id.replace('-', '_')}"
            spec = importlib.util.find_spec(module_name)
            assert spec is not None, f"No adapter module for {tool.tool_id!r}"
        assert tool.prerequisites
        assert tool.limitations
        assert not evaluate_eligibility(tool).installable
    assert {"headroom", "graphify", "promptfoo", "playwright-mcp"} <= {
        tool.tool_id for tool in catalog.tools
    }


def test_assignment_deliverable_has_30_catalog_entries() -> None:
    # Keep the agreed deliverable size separate from general catalog validation.
    assert len(load_catalog().tools) == 30


def test_reviewed_license_scope_preserves_upstream_exceptions() -> None:
    catalog = load_catalog()
    assert "enterprise" in catalog.get("litellm").license_scope
    assert "ee/" in catalog.get("langfuse").license_scope
    assert catalog.get("serena").license == "GPL-3.0-or-later"
    assert "LICENSE-CODE" in catalog.get("autogen").license_scope
    assert "22.22.0" in " ".join(catalog.get("promptfoo").prerequisites)
    assert "3.11" in " ".join(catalog.get("graphify").prerequisites)


def test_category_filter_is_deterministic_and_does_not_mutate_catalog() -> None:
    catalog = load_catalog()
    before = catalog.model_dump_json()
    selected = filter_catalog(catalog, category=Category.EVALUATION)
    assert [tool.tool_id for tool in selected] == [
        "deepeval",
        "inspect-ai",
        "promptfoo",
        "ragas",
        "trulens",
    ]
    assert catalog.model_dump_json() == before
    assert filter_catalog(catalog, installable_only=True) == []


def test_invalid_catalog_files_produce_actionable_errors(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    with pytest.raises(CatalogError, match="bad.json"):
        load_catalog(path)
    path.write_text("{not json}")
    with pytest.raises(CatalogError, match="Cannot load catalog"):
        load_catalog(path)
    path.write_bytes(b"\xff")
    with pytest.raises(CatalogError):
        load_catalog(path)


@pytest.mark.parametrize("size", [1, 5, 31])
def test_local_catalog_round_trip(tmp_path: Path, size: int) -> None:
    catalog = Catalog(tools=[entry(tool_id=f"tool-{index}") for index in range(size)])
    path = tmp_path / "catalog.json"
    path.write_text(catalog.model_dump_json())
    assert load_catalog(path) == catalog


def test_indexed_lookup_after_json_round_trip() -> None:
    catalog = Catalog(tools=[entry(), entry(tool_id="other-tool")])
    restored = Catalog.model_validate_json(catalog.model_dump_json())
    for tool in restored.tools:
        assert restored.get(tool.tool_id) is tool
    with pytest.raises(KeyError, match="missing-tool"):
        restored.get("missing-tool")
    assert set(restored.model_dump()) == {"schema_version", "tools"}


def test_catalog_membership_and_ids_cannot_invalidate_index() -> None:
    source = [entry()]
    catalog = Catalog(tools=source)
    source.append(entry(tool_id="other-tool"))
    assert len(catalog.tools) == 1
    with pytest.raises(ValidationError, match="frozen"):
        catalog.tools = ()
    with pytest.raises(TypeError):
        catalog.tools[0] = entry(tool_id="replacement")
    with pytest.raises(ValidationError, match="frozen"):
        catalog.get("example-tool").tool_id = "renamed-tool"
    assert catalog.get("example-tool") is catalog.tools[0]
    with pytest.raises(KeyError):
        catalog.get("renamed-tool")


@pytest.mark.parametrize("deep", [False, True])
def test_copied_catalog_index_matches_its_entries(deep: bool) -> None:
    catalog = Catalog(tools=[entry()])
    copied = catalog.model_copy(deep=deep)
    assert copied.get("example-tool") is copied.tools[0]
    assert (copied.get("example-tool") is catalog.get("example-tool")) is not deep


def test_replacing_entries_rebuilds_index_and_preserves_original() -> None:
    catalog = Catalog(tools=[entry()])
    replacement = entry(tool_id="replacement").model_dump(mode="json")
    copied = catalog.model_copy(update={"tools": [replacement]})
    assert copied.get("replacement") is copied.tools[0]
    with pytest.raises(KeyError):
        copied.get("example-tool")
    assert catalog.get("example-tool") is catalog.tools[0]
    with pytest.raises(ValidationError, match="IDs must be unique"):
        catalog.model_copy(update={"tools": [entry(), entry()]})
    with pytest.raises(ValidationError, match="Extra inputs"):
        catalog.model_copy(update={"toools": []})


def test_duplicate_ids_and_dangling_relationships_are_rejected() -> None:
    with pytest.raises(ValidationError, match="IDs must be unique"):
        Catalog(tools=[entry(), entry()])
    for field in ("conflicts", "alternatives"):
        for reference in ("missing-tool", "example-tool"):
            with pytest.raises(ValidationError, match="invalid related tool reference"):
                Catalog(tools=[entry(**{field: [reference]})])


@pytest.mark.parametrize(
    "changes",
    [
        {"category": "made-up"},
        {"prerequisites": []},
        {"license": None},
        {"license": "not-an-open-source-license"},
        {"sources": []},
        {"reviewed_on": "not-a-date"},
        {"supported_platforms": ["macos", "macos"]},
        {"licence_scope": "typo"},
    ],
)
def test_incomplete_or_inconsistent_reviews_are_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        entry(**changes)


def test_license_review_requires_the_actual_license_reference() -> None:
    source = {"kind": "readme", "url": "https://example.invalid/README", "sha256": "a" * 64}
    with pytest.raises(ValidationError, match="license source"):
        entry(sources=[source])


@pytest.mark.parametrize("changes", [{}, {"kind": "requirements"}, {"sha256": "c" * 64}])
def test_duplicate_source_urls_are_rejected(changes: dict[str, str]) -> None:
    sources = entry().model_dump(mode="json")["sources"]
    sources.append({**sources[0], **changes})
    with pytest.raises(ValidationError, match="sources must contain unique URLs"):
        entry(sources=sources)


@pytest.mark.parametrize("use_copy", [False, True])
def test_license_gate_rechecks_entries_changed_after_validation(use_copy: bool) -> None:
    tool = entry()
    if use_copy:
        tool = tool.model_copy(update={"license": "proprietary"})
    else:
        tool.license = "proprietary"
    assert "license-unresolved" in codes(tool, ready_context())


def test_metadata_alone_cannot_mark_an_entry_installable() -> None:
    result = evaluate_eligibility(entry())
    assert not result.installable
    assert {reason.code for reason in result.reasons} >= {
        "adapter-unregistered",
        "platform-unknown",
        "assistant-unknown",
        "prerequisites-unverified",
    }


def test_a_runtime_must_supply_all_readiness_checks() -> None:
    result = evaluate_eligibility(entry(), ready_context())
    assert result.installable
    assert result.reasons == []
    catalog = Catalog(tools=[entry()])
    assert filter_catalog(catalog, installable_only=True, context=ready_context()) == list(
        catalog.tools
    )


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"registered_adapters": []}, "adapter-unregistered"),
        ({"platform": None}, "platform-unknown"),
        ({"platform": "windows"}, "platform-unsupported"),
        ({"assistant": None}, "assistant-unknown"),
        ({"assistant": "claude-code"}, "assistant-unsupported"),
        ({"prerequisite_checks": {}}, "prerequisites-unverified"),
        ({"prerequisite_checks": {"example-tool": "failed"}}, "prerequisites-failed"),
        ({"prerequisite_checks": {"example-tool": "blocked"}}, "prerequisites-failed"),
        ({"prerequisite_checks": {"example-tool": "skipped"}}, "prerequisites-unverified"),
    ],
)
def test_missing_or_failed_runtime_checks_block_setup(
    changes: dict[str, object], expected: str
) -> None:
    assert expected in codes(entry(), ready_context(**changes))


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"license": None, "license_review": "unresolved"}, "license-unresolved"),
        ({"availability": "catalog_only"}, "adapter-unavailable"),
        ({"supported_platforms": []}, "platform-unverified"),
        ({"supported_assistants": []}, "assistant-unverified"),
    ],
)
def test_unknown_or_unavailable_metadata_blocks_setup(
    changes: dict[str, object], expected: str
) -> None:
    assert expected in codes(entry(**changes), ready_context())


@pytest.mark.parametrize("candidate", ["example-tool", "other-tool"])
def test_a_known_conflict_blocks_both_selection_orders(candidate: str) -> None:
    tool = entry(conflicts=["other-tool"])
    catalog = Catalog(tools=[tool, entry(tool_id="other-tool", conflicts=["example-tool"])])
    context = ready_context(
        registered_adapters=[candidate], prerequisite_checks={candidate: "succeeded"}
    )
    assert evaluate_eligibility(catalog.get(candidate), context).installable
    context.selected_tools = [tool.tool_id for tool in catalog.tools if tool.tool_id != candidate]
    assert codes(catalog.get(candidate), context) == {"selection-conflict"}


@pytest.mark.parametrize("reverse", [False, True])
def test_one_sided_conflicts_are_rejected_regardless_of_entry_order(reverse: bool) -> None:
    tools = [entry(conflicts=["other-tool"]), entry(tool_id="other-tool")]
    if reverse:
        tools.reverse()
    with pytest.raises(ValidationError, match="conflict with 'other-tool' must be reciprocal"):
        Catalog(tools=tools)


def test_alternatives_can_be_one_sided() -> None:
    catalog = Catalog(tools=[entry(alternatives=["other-tool"]), entry(tool_id="other-tool")])
    assert catalog.get("example-tool").alternatives == ["other-tool"]


def test_environment_profile_is_consumed_without_inventing_runtime_readiness() -> None:
    profile = ProjectProfile(
        project_root="./sample",
        assistant="codex",
        operating_system="Darwin release details (arm64)",
        facts={"os": ["Darwin"]},
    )
    context = EligibilityContext.from_profile(profile)
    assert context.platform == Platform.MACOS
    assert context.assistant == "codex"
    assert context.prerequisite_checks == {}
    assert context.registered_adapters == []
    unknown = EligibilityContext.from_profile(ProjectProfile(project_root="./sample"))
    assert unknown.platform is None
    assert unknown.assistant is None


def test_catalog_json_has_only_documented_top_level_fields(tmp_path: Path) -> None:
    data = Catalog(tools=[entry()]).model_dump(mode="json")
    data["install_command"] = "not part of a catalog"
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(data))
    with pytest.raises(CatalogError, match="Extra inputs"):
        load_catalog(path)


@pytest.mark.parametrize("facts", [{}, {"os": []}])
@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("Darwin Kernel Version 27.0.0", Platform.MACOS),
        ("Linux 6.8.0 (x86_64)", Platform.LINUX),
        ("Windows 11 (AMD64)", Platform.WINDOWS),
        ("mAcOS 15.0", Platform.MACOS),
        ("FreeBSD 14.0", None),
    ],
)
def test_descriptive_os_fallback(
    facts: dict[str, list[str]], description: str, expected: Platform | None
) -> None:
    profile = ProjectProfile(project_root="./sample", facts=facts, operating_system=description)
    context = EligibilityContext.from_profile(profile)
    assert context.platform == expected
    if expected is None:
        assert "platform-unknown" in codes(entry(), context)


def test_canonical_os_fact_takes_precedence_over_description() -> None:
    profile = ProjectProfile(
        project_root="./sample",
        facts={"os": ["Linux"]},
        operating_system="Darwin Kernel Version 27.0.0",
    )
    assert EligibilityContext.from_profile(profile).platform == Platform.LINUX

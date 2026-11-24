"""Direct-API tests for the project report builder and renderers."""

from pathlib import Path

from stackwinnow.report import ProjectReport, ReportError, build_report

FIXED = "2026-01-01T00:00:00+00:00"


def _node_project(
    root: Path, manifest: str = '{"devDependencies":{"promptfoo":"0.125.1"}}'
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text(manifest, encoding="utf-8")
    return root


def test_build_report_round_trips_through_pydantic(tmp_path: Path) -> None:
    project = _node_project(tmp_path / "proj")
    report = build_report(
        project,
        goals=["Evaluate answers"],
        selected_tools=["promptfoo"],
        platform="macos",
        generated_at=FIXED,
    )
    restored = ProjectReport.model_validate_json(report.model_dump_json())
    assert restored == report
    assert report.generated_at == FIXED
    assert report.project_root == str(project)


def test_markdown_is_deterministic_and_has_expected_sections(tmp_path: Path) -> None:
    project = _node_project(tmp_path / "proj")
    report = build_report(
        project, goals=["Evaluate answers"], selected_tools=["promptfoo"], generated_at=FIXED
    )
    first = report.to_markdown()
    assert report.to_markdown() == first  # deterministic for a fixed timestamp
    for fragment in (
        f"# StackWinnow report: {project}",
        "Read-only: no tools were installed, configured, or run.",
        "## Project",
        "## Recommended tools",
        "### promptfoo (`promptfoo`) — selected",
        "- Integration: catalog only (no StackWinnow adapter)",
        "## Caveats",
    ):
        assert fragment in first


def test_payload_has_single_schema_version_and_derived_ready(tmp_path: Path) -> None:
    project = _node_project(tmp_path / "proj")
    report = build_report(project, selected_tools=["promptfoo"], generated_at=FIXED)
    payload = report.to_payload()
    assert payload["schema_version"] == 1
    import json

    assert json.dumps(payload).count('"schema_version"') == 1
    assert payload["recommendation"]["complete"] is True
    assert payload["verification"] is None
    assert payload["ready"] == report.ready


def test_verification_requires_a_selected_tool(tmp_path: Path) -> None:
    project = _node_project(tmp_path / "proj")
    try:
        build_report(project, include_verification=True, generated_at=FIXED)
    except ReportError:
        return
    raise AssertionError("include_verification without a tool should raise ReportError")


def test_verification_section_is_present_when_requested(tmp_path: Path) -> None:
    project = _node_project(tmp_path / "proj")
    report = build_report(
        project, selected_tools=["promptfoo"], include_verification=True, generated_at=FIXED
    )
    assert report.verification is not None
    assert [tool.tool_id for tool in report.verification.tools] == ["promptfoo"]
    markdown = report.to_markdown()
    assert "## Verification" in markdown
    payload = report.to_payload()
    assert payload["verification"]["tools"][0]["tool_id"] == "promptfoo"

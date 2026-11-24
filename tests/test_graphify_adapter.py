"""Graphify previews cannot imply installation, ownership, or connectivity."""

from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from stackwinnow.adapters.graphify import (
    GRAPH_PATH,
    WHEEL_SHA256,
    GraphifyError,
    GraphifyPlan,
    RelationshipExpectation,
    check_relationship,
    index_command,
    plan_graphify,
    relationship_query,
)
from stackwinnow.catalog import load_catalog
from stackwinnow.plan import PreflightError


@pytest.fixture
def expected():
    return RelationshipExpectation.model_validate_json(
        (Path(__file__).parent / "fixtures/graphify-relationship.json").read_text()
    )


@pytest.fixture
def graph(expected):
    return {
        "nodes": [
            {"id": "caller", "source_file": expected.caller_file, "label": expected.caller_label},
            {"id": "callee", "source_file": expected.callee_file, "label": expected.callee_label},
        ],
        "edges": [
            {"source": "caller", "target": "callee", "relation": "calls", "confidence": "EXTRACTED"}
        ],
    }


def test_preview_is_read_only_pinned_and_explicitly_blocked(fixture_project, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Preview must not execute commands")

    monkeypatch.setattr("subprocess.Popen", forbidden)
    root = fixture_project.root
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    plan = plan_graphify(root, platform="macos", assistant="codex")
    assert plan.artifact.distribution == "graphifyy" and plan.artifact.version == "0.9.114"
    assert plan.artifact.requires_python == ">=3.11.5,<3.15"
    assert not plan.ready_to_apply and plan.blockers
    assert not plan.artifact.dependencies_locked
    assert not plan.preflight.is_ready_to_apply
    assert {check.status for check in plan.preflight.checks} == {"blocked"}
    assert plan.installation.tool_ids == ["graphify"]
    # Executable modes now exist, but this old command remains a non-executable preview.
    assert load_catalog().get("graphify").availability == "adapter_available"
    assert GraphifyPlan.model_validate_json(plan.model_dump_json()) == plan
    assert before == {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    assert not (root / ".stackwinnow").exists()
    install = plan.commands[2]
    assert install.network_required
    assert install.argv[-1] == f"{plan.artifact.url}#sha256={WHEEL_SHA256}"
    assert "--only-binary=:all:" in install.argv
    assert not any("uninstall" in command.argv for command in plan.commands)


def test_index_and_query_keep_paths_as_arguments_and_disable_user_side_effects(
    tmp_path, expected, graph
):
    root = tmp_path / "space and ; shell characters"
    root.mkdir()
    python = root / "venv/bin/python"
    command = index_command(root, python)
    assert command.argv[:5] == [str(python), "-I", "-m", "graphify", "extract"]
    assert command.argv[5] == str(root.resolve())
    assert "--code-only" in command.argv and "--no-cluster" in command.argv
    assert command.argv[-2:] == ["--exclude", ".stackwinnow"]
    assert command.environment["GRAPHIFY_NO_AUTO_REFRESH"] == "1"
    assert command.environment["GRAPHIFY_QUERY_LOG_DISABLE"] == "1"
    assert Path(command.environment["HOME"]).is_relative_to(root.resolve())
    assert not command.network_required
    query = relationship_query(root, python, check_relationship(graph, expected))
    assert query.argv[4:7] == ["path", "caller", "callee"]
    assert query.argv[-3:] == ["--graph", str(root.resolve() / GRAPH_PATH), "--directed"]
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("platform,assistant", [("linux", "codex"), ("macos", "cursor"), ("", "")])
def test_unsupported_targets_are_not_silently_accepted(tmp_path, platform, assistant):
    with pytest.raises(GraphifyError, match="macOS/Codex"):
        plan_graphify(tmp_path, platform=platform, assistant=assistant)


@pytest.mark.parametrize(
    "relative",
    [
        ".stackwinnow",
        ".stackwinnow/receipts.json",
        ".stackwinnow/envs/graphify/python",
        ".stackwinnow/graphify/index/graphify-out",
        ".stackwinnow/graphify/home",
    ],
)
def test_symlinked_managed_paths_are_rejected_before_preflight(tmp_path, relative):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(outside, target_is_directory=True)
    with pytest.raises(GraphifyError, match="managed path"):
        plan_graphify(root, platform="macos", assistant="codex")
    assert list(outside.iterdir()) == []


def test_nonexistent_or_non_directory_project_is_rejected(tmp_path):
    for root in (tmp_path / "missing", tmp_path / "file"):
        if root.name == "file":
            root.write_text("not a project")
        with pytest.raises(GraphifyError):
            plan_graphify(root, platform="macos", assistant="codex")


def test_corrupt_receipts_do_not_become_a_ready_preview(tmp_path):
    (tmp_path / ".stackwinnow").mkdir()
    (tmp_path / ".stackwinnow/receipts.json").write_text("{broken")
    with pytest.raises(PreflightError):
        plan_graphify(tmp_path, platform="macos", assistant="codex")


def test_supplied_graph_evidence_is_exact_and_inputs_are_unchanged(graph, expected):
    # A function with the same name in another file must not make the match ambiguous.
    graph["nodes"].append(
        {"id": "other", "source_file": "other.py", "label": expected.caller_label}
    )
    before = deepcopy(graph)
    result = check_relationship(graph, expected)
    assert result.status == "succeeded"
    assert (result.source_node_id, result.target_node_id) == ("caller", "callee")
    assert result.evidence[0].source == "supplied Graphify graph"
    assert graph == before


@pytest.mark.parametrize("change", [None, "removed", "wrong-relation", "inferred"])
def test_recursive_call_requires_an_explicit_extracted_self_edge(tmp_path, change):
    expected = RelationshipExpectation(
        caller_file="recursive.py",
        caller_label="factorial()",
        callee_file="recursive.py",
        callee_label="factorial()",
    )
    graph = {
        "nodes": [
            {"id": "recursive_factorial", "source_file": "recursive.py", "label": "factorial()"}
        ],
        "edges": [
            {
                "source": "recursive_factorial",
                "target": "recursive_factorial",
                "relation": "calls",
                "confidence": "EXTRACTED",
            }
        ],
    }
    if change == "removed":
        graph["edges"] = []
    elif change == "wrong-relation":
        graph["edges"][0]["relation"] = "references"
    elif change == "inferred":
        graph["edges"][0]["confidence"] = "INFERRED"
    result = check_relationship(graph, expected)
    if change is None:
        assert result.status == "succeeded"
        assert result.source_node_id == result.target_node_id == "recursive_factorial"
        query = relationship_query(tmp_path, "/python", result)
        assert query.argv[4:] == [
            "explain",
            "recursive_factorial",
            "--all",
            "--graph",
            str(tmp_path / GRAPH_PATH),
        ]
    else:
        assert result.status == "failed"
        with pytest.raises(GraphifyError, match="successful relationship"):
            relationship_query(tmp_path, "/python", result)


def test_expected_source_paths_preserve_whitespace(graph, expected):
    spelling = " sample_app/greetings.py "
    exact = RelationshipExpectation.model_validate(
        {**expected.model_dump(), "caller_file": spelling}
    )
    assert exact.caller_file == spelling
    assert check_relationship(graph, exact).status == "failed"
    graph["nodes"][0]["source_file"] = spelling
    assert check_relationship(graph, exact).status == "succeeded"


def test_external_preflight_observation_never_enables_apply(tmp_path, monkeypatch):
    executable = tmp_path / "external-graphify"
    executable.write_text("external tool")
    monkeypatch.setattr("stackwinnow.plan.shutil.which", lambda name: str(executable))
    plan = plan_graphify(tmp_path, platform="macos", assistant="codex")
    assert {check.status for check in plan.preflight.checks} == {"blocked"}
    assert not plan.preflight.is_ready_to_apply
    assert not plan.ready_to_apply and plan.blockers
    assert not (tmp_path / ".stackwinnow").exists()


@pytest.mark.parametrize(
    "change",
    ["missing", "reverse", "wrong-relation", "inferred", "duplicate", "ambiguous", "wrong-file"],
)
def test_wrong_relationship_cannot_pass_or_produce_a_query(graph, expected, tmp_path, change):
    if change == "missing":
        graph["edges"] = []
    elif change == "reverse":
        graph["edges"][0].update(source="callee", target="caller")
    elif change == "wrong-relation":
        graph["edges"][0]["relation"] = "imports"
    elif change == "inferred":
        graph["edges"][0]["confidence"] = "INFERRED"
    elif change == "duplicate":
        graph["nodes"].append(dict(graph["nodes"][0]))
    elif change == "ambiguous":
        graph["nodes"].append({**graph["nodes"][0], "id": "other"})
    else:
        graph["nodes"][0]["source_file"] = "another/greetings.py"
    result = check_relationship(graph, expected)
    assert result.status == "failed"
    assert result.source_node_id is result.target_node_id is None
    with pytest.raises(GraphifyError, match="successful relationship"):
        relationship_query(tmp_path, "/python", result)


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        {},
        {"nodes": {}, "edges": []},
        {"nodes": [None], "edges": []},
        {"nodes": [{"id": []}], "edges": []},
        {"nodes": [{"id": "node"}], "edges": [{"source": "node", "target": "missing"}]},
        {"nodes": [{"id": "node"}], "edges": [{"source": [], "target": "node"}]},
    ],
)
def test_malformed_graph_reports_failure(data, expected):
    assert check_relationship(data, expected).status == "failed"


@pytest.mark.parametrize("path", ["../outside.py", "/absolute.py", "./source.py", "a\\b.py"])
def test_expectations_reject_non_project_paths(path, expected):
    with pytest.raises(ValidationError):
        RelationshipExpectation.model_validate({**expected.model_dump(), "caller_file": path})

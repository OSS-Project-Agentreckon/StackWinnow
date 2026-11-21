"""Real offline Graphify indexing/query evidence; no assistant connectivity claim."""

import json
import os
import platform
from pathlib import Path

import pytest

from stackwinnow.adapters.graphify import (
    GRAPH_PATH,
    VERSION,
    RelationshipExpectation,
    check_relationship,
    index_command,
    relationship_query,
)
from stackwinnow.runner import run_command

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("recursive", [False, True], ids=["cross-file-call", "recursive-call"])
def test_real_graphify_index_query_negative_control_and_repeat(
    fixture_project, subprocess_env, recursive
):
    selected = os.environ.get("STACKWINNOW_GRAPHIFY_PYTHON")
    if not selected:
        pytest.skip(
            "Set STACKWINNOW_GRAPHIFY_PYTHON to an isolated graphifyy==0.9.114 interpreter."
        )
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        pytest.skip("Initial Graphify evidence targets macOS arm64.")
    python = Path(selected).absolute()
    assert python.is_file(), "The selected Graphify interpreter is missing."
    root = fixture_project.root.resolve()
    if recursive:
        (root / "recursive.py").write_text(
            "def factorial(n):\n    if n <= 1:\n        return 1\n    return n * factorial(n - 1)\n"
        )
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    command = index_command(root, python)
    environment = {**subprocess_env, **command.environment}
    for key in ("HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME"):
        Path(environment[key]).mkdir(parents=True, exist_ok=True)
    version = run_command(
        [str(python), "-I", "-m", "graphify", "--version"],
        cwd=root,
        timeout=30,
        extra_env=environment,
    )
    assert version.succeeded and version.stdout.strip() == f"graphify {VERSION}"
    expected = RelationshipExpectation.model_validate_json(
        (Path(__file__).parents[1] / "fixtures/graphify-relationship.json").read_text()
    )
    if recursive:
        expected = RelationshipExpectation(
            caller_file="recursive.py",
            caller_label="factorial()",
            callee_file="recursive.py",
            callee_label="factorial()",
        )
    for attempt in range(2):
        indexed = run_command(
            command.argv, cwd=command.cwd, timeout=command.timeout_seconds, extra_env=environment
        )
        assert indexed.succeeded, indexed.stderr
        graph = json.loads((root / GRAPH_PATH).read_text())
        assert graph["input_tokens"] == graph["output_tokens"] == 0
        evidence = check_relationship(graph, expected)
        assert evidence.status == "succeeded", evidence.message
        query = relationship_query(root, python, evidence)
        result = run_command(
            query.argv, cwd=query.cwd, timeout=query.timeout_seconds, extra_env=environment
        )
        assert result.succeeded, result.stderr
        if recursive:
            assert evidence.source_node_id == evidence.target_node_id
            assert "Node: factorial()" in result.stdout
            assert "--> factorial() [calls] [EXTRACTED]" in result.stdout
        else:
            assert "greet() --calls [EXTRACTED]--> normalize_name()" in result.stdout
        wrong = query.argv.copy()
        wrong[5 if recursive else 6] = "stackwinnow_missing_fixture_symbol"
        negative = run_command(
            wrong, cwd=query.cwd, timeout=query.timeout_seconds, extra_env=environment
        )
        assert negative.returncode == 4 and not negative.succeeded
        graph["edges"] = [edge for edge in graph["edges"] if edge.get("relation") != "calls"]
        assert check_relationship(graph, expected).status == "failed"
    assert all((root / path).read_bytes() == content for path, content in before.items())
    assert not (root / ".codex").exists() and not (root / "AGENTS.md").exists()
    assert not (root / "graphify-out").exists()

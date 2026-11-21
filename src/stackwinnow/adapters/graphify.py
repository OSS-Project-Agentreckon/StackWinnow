"""Read-only Graphify recipe previews and known-relationship evidence checks.

Managed apply and client verification await the shared verification framework
and ownership support for upstream's Markdown/skill edits. A preview never
executes its commands or declares an existing installation owned.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, field_validator

from stackwinnow.catalog import EligibilityContext, load_catalog
from stackwinnow.contracts import (
    Contract,
    EvidenceRef,
    InstallPlan,
    NonEmptyText,
    OperationResult,
    OperationStatus,
    PlanStep,
    UntrimmedText,
)
from stackwinnow.environments import bootstrap_pip_args, create_venv_args, python_env_path
from stackwinnow.plan import PreflightReport, check_plan

VERSION = "0.9.114"
WHEEL_SHA256 = "cf3cb57e87840a0c6ef7399578a95ad7ff6a83539dc71dcef0465b1b7f3a3453"
WHEEL_URL = (
    "https://files.pythonhosted.org/packages/ef/4f/"
    "44f9f4271c4de7c9b65777a01f3ce28dc6a1ca04360f812fa942371a4827/"
    "graphifyy-0.9.114-py3-none-any.whl"
)
STATE_PATH = ".stackwinnow/graphify"
INDEX_PATH = f"{STATE_PATH}/index"
GRAPH_PATH = f"{INDEX_PATH}/graphify-out/graph.json"


class GraphifyError(ValueError):
    """An invalid preview request or unsupported project path."""


class GraphifyArtifact(Contract):
    distribution: Literal["graphifyy"] = "graphifyy"
    version: Literal["0.9.114"] = VERSION
    url: str = WHEEL_URL
    sha256: str = WHEEL_SHA256
    license: Literal["Apache-2.0"] = "Apache-2.0"
    requires_python: Literal[">=3.11.5,<3.15"] = ">=3.11.5,<3.15"
    dependencies_locked: Literal[False] = False


class CommandPreview(Contract):
    """Arguments for review, not a serialized executable plan accepted by apply."""

    argv: list[UntrimmedText]
    cwd: UntrimmedText
    environment: dict[str, str]
    timeout_seconds: int = Field(gt=0)
    network_required: bool = False


class GraphifyPlan(Contract):
    schema_version: Literal[1] = 1
    tool_id: Literal["graphify"] = "graphify"
    phase: Literal["preview-only"] = "preview-only"
    project_root: UntrimmedText
    target_platform: Literal["macos"]
    assistant: Literal["codex"]
    artifact: GraphifyArtifact
    graph_path: str = GRAPH_PATH
    installation: InstallPlan
    commands: list[CommandPreview]
    preflight: PreflightReport
    ready_to_apply: Literal[False] = False
    blockers: list[NonEmptyText]
    notes: list[NonEmptyText]


class RelationshipExpectation(Contract):
    """Exact file and label pairs disambiguate identically named functions."""

    caller_file: UntrimmedText
    caller_label: NonEmptyText
    callee_file: UntrimmedText
    callee_label: NonEmptyText

    @field_validator("caller_file", "callee_file")
    @classmethod
    def relative_source(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or not path.parts
            or ".." in path.parts
            or "\\" in value
            or "\x00" in value
            or path.as_posix() != value
        ):
            raise ValueError("Expected source must be a normalized project-relative path.")
        return value


class RelationshipCheck(OperationResult):
    """Evidence in a supplied graph only; does not establish freshness or client connectivity."""

    source_node_id: str | None = None
    target_node_id: str | None = None


def _root(project_root: str | Path) -> Path:
    try:
        root = Path(project_root).resolve(strict=True)
        if not root.is_dir():
            raise GraphifyError("Select an existing project directory.")
        # Preflight reads receipts. Reject links before allowing that read, including
        # links that point inside the project: path existence is not ownership.
        for relative in (
            ".stackwinnow",
            ".stackwinnow/receipts.json",
            ".stackwinnow/envs",
            ".stackwinnow/envs/graphify",
            ".stackwinnow/envs/graphify/python",
            STATE_PATH,
            INDEX_PATH,
            f"{STATE_PATH}/home",
            f"{STATE_PATH}/home/.cache",
            f"{STATE_PATH}/home/.config",
            f"{INDEX_PATH}/graphify-out",
            GRAPH_PATH,
        ):
            candidate = root / relative
            try:
                mode = candidate.lstat().st_mode
            except FileNotFoundError:
                continue
            is_file = relative in (".stackwinnow/receipts.json", GRAPH_PATH)
            if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) if is_file else stat.S_ISDIR(mode)):
                raise GraphifyError("A Graphify managed path is a link or has an unexpected type.")
        return root
    except (OSError, RuntimeError, ValueError) as exc:
        if isinstance(exc, GraphifyError):
            raise
        raise GraphifyError("Cannot inspect the selected project or its managed paths.") from None


def _environment(root: Path) -> dict[str, str]:
    private_home = root / STATE_PATH / "home"
    return {
        "HOME": str(private_home),
        "XDG_CONFIG_HOME": str(private_home / ".config"),
        "XDG_CACHE_HOME": str(private_home / ".cache"),
        "GRAPHIFY_OUT": "graphify-out",
        "GRAPHIFY_NO_AUTO_REFRESH": "1",
        "GRAPHIFY_QUERY_LOG_DISABLE": "1",
        "PYTHONHASHSEED": "0",
        "PIP_CONFIG_FILE": "/dev/null",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    }


def index_command(project_root: str | Path, python: str | Path) -> CommandPreview:
    """Describe code-only extraction with one worker and explicitly scoped output."""
    root = _root(project_root)
    return CommandPreview(
        argv=[
            str(python),
            "-I",
            "-m",
            "graphify",
            "extract",
            str(root),
            "--code-only",
            "--no-cluster",
            "--max-workers",
            "1",
            "--out",
            str(root / INDEX_PATH),
            "--exclude",
            ".stackwinnow",
        ],
        cwd=str(root),
        environment=_environment(root),
        timeout_seconds=120,
    )


def plan_graphify(project_root: str | Path, *, platform: str, assistant: str) -> GraphifyPlan:
    """Preview the macOS/Codex candidate recipe, without installation or configuration."""
    if platform != "macos" or assistant != "codex":
        raise GraphifyError("The initial Graphify recipe targets macOS/Codex only.")
    root = _root(project_root)
    venv = python_env_path(str(root), "graphify")
    # This is the declared macOS target layout, even when previewed on another OS.
    python = venv / "bin/python"
    descriptions = (
        ("install", "Create an isolated environment and install the hash-pinned Graphify wheel."),
        ("index", "Index project code locally into the declared Graphify output directory."),
        ("configure", "Configure only the selected client after ownership support is available."),
        ("verify", "Verify a known relationship and separately exercise the selected client."),
    )
    installation = InstallPlan(
        project_root=str(root),
        assistant=assistant,
        tool_ids=["graphify"],
        steps=[
            PlanStep(step_id=f"graphify-{key}", tool_id="graphify", description=text)
            for key, text in descriptions
        ],
    )
    context = EligibilityContext(
        platform=platform, assistant=assistant, selected_tools=["graphify"]
    )
    preflight = check_plan(installation, catalog=load_catalog(), context=context)
    command_args = [
        [sys.executable, "-I", *create_venv_args(venv)[1:]],
        # Explicit POSIX path keeps cross-platform previews consistent with the target.
        [str(python), "-I", *bootstrap_pip_args(venv)[1:]],
        [
            str(python),
            "-I",
            "-m",
            "pip",
            "--isolated",
            "install",
            "--disable-pip-version-check",
            "--only-binary=:all:",
            f"{WHEEL_URL}#sha256={WHEEL_SHA256}",
        ],
    ]
    return GraphifyPlan(
        project_root=str(root),
        target_platform=platform,
        assistant=assistant,
        artifact=GraphifyArtifact(),
        installation=installation,
        preflight=preflight,
        commands=[
            CommandPreview(
                argv=argv,
                cwd=str(root),
                environment=_environment(root),
                timeout_seconds=600 if index == 2 else 60,
                network_required=index == 2,
            )
            for index, argv in enumerate(command_args)
        ]
        + [index_command(root, python)],
        blockers=[
            "Managed Graphify apply is not implemented; these commands are previews only.",
            "Shared verification and actual Codex connectivity checks are pending.",
            "Owned Markdown/skill changes are required before automating upstream Codex setup.",
            "Host Python/platform prerequisites and the dependency set need validation at apply time.",
        ],
        notes=[
            "The wheel identity and hash are pinned; transitive dependencies are not yet locked.",
            "Package downloads need network access. Code-only extraction needs no model API key.",
            "Upstream Codex setup affects AGENTS.md, .codex/skills/graphify, and .codex/hooks.json; "
            "this preview does not edit them or invoke upstream install/uninstall.",
            "Private child HOME/cache paths, query-log opt-out, and disabled auto-refresh "
            "must be retained by future execution. No ownership is claimed by a preview.",
            "A recorded preflight skip or external installation is not proof of an eligible, "
            "owned, functional Graphify installation. Catalog availability stays catalog_only.",
            f"Bootstrap interpreter: {sys.executable}; requires Python >=3.11.5,<3.15.",
        ],
    )


def check_relationship(graph: object, expected: RelationshipExpectation) -> RelationshipCheck:
    """Check a raw 0.9.114 graph for one exact, directed, EXTRACTED calls edge.

    The caller owns bounded loading, fresh index execution and provenance checks.
    Do not interpret this evidence check as a complete functional/client check.
    """
    expected = RelationshipExpectation.model_validate_json(expected.model_dump_json())

    def failure(message: str) -> RelationshipCheck:
        return RelationshipCheck(status=OperationStatus.FAILED, tool_id="graphify", message=message)

    if not isinstance(graph, dict):
        return failure("Expected a raw Graphify graph object.")
    nodes, edges = graph.get("nodes"), graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return failure("Expected raw Graphify nodes and edges lists.")
    by_id = {}
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"]:
            return failure("Graph contains an invalid node identifier.")
        if node["id"] in by_id:
            return failure("Graph contains duplicate node identifiers.")
        by_id[node["id"]] = node
    for edge in edges:
        if not isinstance(edge, dict) or any(
            not isinstance(edge.get(key), str) or edge[key] not in by_id
            for key in ("source", "target")
        ):
            return failure("Graph contains an invalid or dangling edge.")
    endpoints = []
    for file, label in (
        (expected.caller_file, expected.caller_label),
        (expected.callee_file, expected.callee_label),
    ):
        matches = [
            node_id
            for node_id, node in by_id.items()
            if node.get("source_file") == file and node.get("label") == label
        ]
        if len(matches) != 1:
            return failure("Expected function is missing or ambiguous in its source file.")
        endpoints.append(matches[0])
    source, target = endpoints
    if not any(
        edge["source"] == source
        and edge["target"] == target
        and edge.get("relation") == "calls"
        and edge.get("confidence") == "EXTRACTED"
        for edge in edges
    ):
        return failure("Expected directed, extracted call relationship was not found.")
    return RelationshipCheck(
        status=OperationStatus.SUCCEEDED,
        tool_id="graphify",
        message="The supplied graph contains the expected extracted call relationship.",
        source_node_id=source,
        target_node_id=target,
        evidence=[
            EvidenceRef(
                source="supplied Graphify graph",
                detail=f"{expected.caller_file}:{expected.caller_label} calls "
                f"{expected.callee_file}:{expected.callee_label}",
            )
        ],
    )


def relationship_query(
    project_root: str | Path, python: str | Path, check: RelationshipCheck
) -> CommandPreview:
    """Query exact IDs established by the evidence check rather than fuzzy labels."""
    if (
        check.status != OperationStatus.SUCCEEDED
        or not check.source_node_id
        or not check.target_node_id
    ):
        raise GraphifyError("A successful relationship evidence check is required before querying.")
    root = _root(project_root)
    # Upstream path refuses identical endpoints. Explain lists explicit self-edges;
    # the evidence check above must still establish the recursive call itself.
    query = (
        ["explain", check.source_node_id, "--all", "--graph", str(root / GRAPH_PATH)]
        if check.source_node_id == check.target_node_id
        else [
            "path",
            check.source_node_id,
            check.target_node_id,
            "--graph",
            str(root / GRAPH_PATH),
            "--directed",
        ]
    )
    return CommandPreview(
        argv=[str(python), "-I", "-m", "graphify", *query],
        cwd=str(root),
        environment=_environment(root),
        timeout_seconds=30,
    )

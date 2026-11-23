"""Reviewed, staged Graphify indexing with current runtime/source provenance."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field

from stackwinnow.adapters._managed import ManagedStateError, directories, record_for
from stackwinnow.adapters.graphify import (
    GRAPH_PATH,
    INDEX_PATH,
    STATE_PATH,
    GraphifyError,
    RelationshipCheck,
    RelationshipExpectation,
    _root,
    check_relationship,
    index_command,
    relationship_query,
)
from stackwinnow.adapters.graphify_install import validate_graphify_installation
from stackwinnow.adapters.graphify_plan import (
    ENV_PATH,
    Digest,
    GraphifyExecutionPlan,
    SourceSnapshot,
    _digest,
    _json,
    _read_at,
)
from stackwinnow.contracts import (
    Contract,
    EvidenceRef,
    OperationResult,
    OperationStatus,
    UntrimmedText,
)
from stackwinnow.installer import (
    ExecutionRecord,
    InstallerError,
    StepReceipt,
    _now,
    _persist,
    _record_step,
)
from stackwinnow.runner import CommandResult, run_command
from stackwinnow.state.lock import ProjectLockError, project_lock

INDEX_STEP_ID = "graphify-index-code"
PROVENANCE_PATH = f"{STATE_PATH}/provenance.json"
EXCLUDED = (".git", ".stackwinnow", ".venv", "venv", "node_modules", "__pycache__", ".codex")
CommandRunner = Callable[..., CommandResult]


class GraphifyIndexPlan(Contract):
    schema_version: Literal[1] = 1
    tool_id: Literal["graphify"] = "graphify"
    phase: Literal["index-preparation"] = "index-preparation"
    project_root: UntrimmedText
    installation_sha256: Digest
    installation_plan: GraphifyExecutionPlan
    expectation: RelationshipExpectation
    sources: tuple[SourceSnapshot, ...]
    excluded_names: tuple[str, ...] = EXCLUDED
    previous_provenance_sha256: Digest | None = None
    previous_graph_sha256: Digest | None = None


class GraphifyProvenance(Contract):
    schema_version: Literal[1] = 1
    plan: GraphifyIndexPlan
    graph_sha256: Digest


class GraphifyIndexResult(Contract):
    schema_version: Literal[1] = 1
    tool_id: Literal["graphify"] = "graphify"
    scope: Literal["local-index-only"] = "local-index-only"
    dry_run: bool
    indexed: bool = False
    relationship_check: RelationshipCheck | None = None
    record: ExecutionRecord
    results: list[OperationResult] = Field(default_factory=list)


def snapshot_sources(root: Path) -> tuple[SourceSnapshot, ...]:
    """Bound the complete extraction input, rejecting links and special files.

    Extraction uses a copy of precisely this set; ignored names never enter it.
    Empty directories have no content to extract. Manager/client state is excluded.
    """
    found = []
    total = 0

    def unreadable(error):
        raise GraphifyError("Cannot inspect every Graphify source input.") from error

    for directory, subdirs, filenames in os.walk(root, followlinks=False, onerror=unreadable):
        subdirs[:] = sorted(name for name in subdirs if name not in EXCLUDED)
        for name in subdirs:
            if not stat.S_ISDIR((Path(directory) / name).lstat().st_mode):
                raise GraphifyError("Graphify source directories cannot be symlinks.")
        for name in sorted(filenames):
            if name in EXCLUDED:
                continue
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise GraphifyError("Graphify sources must be regular files without aliases.")
            raw = _read_at(root, relative)
            total += len(raw)
            if total > 32 * 1024 * 1024 or len(found) >= 2000:
                raise GraphifyError("Graphify source snapshot exceeds 2000 files / 32 MiB.")
            found.append(SourceSnapshot(path=relative, sha256=_digest(raw)))
    return tuple(sorted(found, key=lambda item: item.path))


def _optional_digest(root: Path, path: str) -> str | None:
    try:
        return _digest(_read_at(root, path))
    except FileNotFoundError:
        return None


def _owned_state(root: Path) -> None:
    record = record_for(root)
    receipt = record.receipt_for(INDEX_STEP_ID)
    if receipt is None:
        if os.path.lexists(root / STATE_PATH) and not record.retained_path("graphify", STATE_PATH):
            raise GraphifyError("Refusing to adopt an unowned Graphify index directory.")
        directories(root, STATE_PATH)
        return
    if (
        not record.is_succeeded(INDEX_STEP_ID, "graphify")
        or receipt.owned_paths != [STATE_PATH]
        or receipt.configuration_intents
        or receipt.configuration_ownership
    ):
        raise GraphifyError("Partial or unfamiliar Graphify index state requires inspection.")
    directories(root, STATE_PATH)
    if not (root / STATE_PATH).is_dir():
        raise GraphifyError("Owned Graphify index directory is missing; inspect before recovery.")
    # A deliberate replan may replace a changed/missing graph, but provenance
    # and receipt ownership must remain intact before that replacement is offered.
    raw = _read_at(root, PROVENANCE_PATH)
    provenance = GraphifyProvenance.model_validate(_json(raw))
    if provenance.plan.project_root != str(root) or receipt.evidence != [
        EvidenceRef(source=GRAPH_PATH, detail=f"sha256:{provenance.graph_sha256}"),
        EvidenceRef(source=PROVENANCE_PATH, detail=f"sha256:{_digest(raw)}"),
    ]:
        raise GraphifyError("Graphify index ownership/provenance changed; inspect it.")


def plan_graphify_index(
    project_root: str | Path,
    *,
    expectation: RelationshipExpectation,
    installation_plan: GraphifyExecutionPlan | None = None,
) -> GraphifyIndexPlan:
    """Review new inputs after installation, including intentional reindexing."""
    try:
        root = _root(project_root)
        recipe, installation = validate_graphify_installation(root, installation_plan)
        _owned_state(root)
        expected = RelationshipExpectation.model_validate(expectation.model_dump())
        sources = snapshot_sources(root)
        if not {expected.caller_file, expected.callee_file} <= {item.path for item in sources}:
            raise GraphifyError("Expected relationship files are absent or excluded from indexing.")
        return GraphifyIndexPlan(
            project_root=str(root),
            installation_sha256=installation,
            installation_plan=recipe,
            expectation=expected,
            sources=sources,
            previous_provenance_sha256=_optional_digest(root, PROVENANCE_PATH),
            previous_graph_sha256=_optional_digest(root, GRAPH_PATH),
        )
    except GraphifyError:
        raise
    except (OSError, ValueError, RuntimeError, RecursionError, ManagedStateError) as exc:
        raise GraphifyError(
            "Cannot plan Graphify indexing; inspect runtime, sources and ownership."
        ) from exc


def _core(plan: GraphifyIndexPlan) -> dict:
    return plan.model_dump(exclude={"previous_provenance_sha256", "previous_graph_sha256"})


def _validate(plan: GraphifyIndexPlan) -> bool:
    current = plan_graphify_index(
        plan.project_root, expectation=plan.expectation, installation_plan=plan.installation_plan
    )
    if current == plan:
        return False
    # Only the exact successful application of this saved plan permits reuse.
    # A new plan made against current state intentionally requests fresh extraction.
    try:
        provenance = GraphifyProvenance.model_validate(
            _json(_read_at(Path(plan.project_root), PROVENANCE_PATH))
        )
    except (OSError, ValueError, GraphifyError) as exc:
        raise GraphifyError("Index inputs changed; generate and review a new index plan.") from exc
    if (
        provenance.plan == plan
        and _core(current) == _core(plan)
        and current.previous_graph_sha256 == provenance.graph_sha256
    ):
        return True
    raise GraphifyError("Index inputs changed; generate and review a new index plan.")


def load_graphify_index_plan(path: str | Path) -> GraphifyIndexPlan:
    try:
        selected = Path(path).absolute()
        plan = GraphifyIndexPlan.model_validate(_json(_read_at(selected.parent, selected.name)))
        _validate(plan)
        return plan
    except (OSError, ValueError, RuntimeError) as exc:
        raise GraphifyError("Invalid or stale index plan; generate and review a new plan.") from exc


def inspect_graphify_index(root: Path) -> tuple[GraphifyProvenance, RelationshipCheck]:
    """Fresh read-only evidence for shared verification and client configuration."""
    _owned_state(root)
    provenance = GraphifyProvenance.model_validate(_json(_read_at(root, PROVENANCE_PATH)))
    _, installation = validate_graphify_installation(root, provenance.plan.installation_plan)
    if (
        provenance.plan.project_root != str(root)
        or provenance.plan.installation_sha256 != installation
        or provenance.plan.excluded_names != EXCLUDED
        or provenance.plan.sources != snapshot_sources(root)
    ):
        raise GraphifyError("Graphify sources or installation changed; review a new index plan.")
    raw = _read_at(root, GRAPH_PATH)
    if _digest(raw) != provenance.graph_sha256:
        raise GraphifyError("Graphify graph changed; review a new index plan.")
    check = check_relationship(_json(raw), provenance.plan.expectation)
    if check.status != OperationStatus.SUCCEEDED:
        raise GraphifyError(check.message)
    return provenance, check


def _publish(root: Path, relative: str, raw: bytes) -> None:
    """Atomic file replacement through anchored parent descriptors."""
    from stackwinnow.configure.patches import _parent

    with _parent(str(root), relative) as (parent, name):
        temporary = f".stackwinnow-{uuid4().hex}.tmp"
        fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent
        )
        try:
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            os.close(fd)
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass


def _execute(
    root: Path, plan: GraphifyIndexPlan, runner: CommandRunner, record: ExecutionRecord
) -> GraphifyIndexResult:
    previous = record.receipt_for(INDEX_STEP_ID)
    owned = (
        list(previous.owned_paths)
        if previous
        else (
            [STATE_PATH]
            if record.retained_path("graphify", STATE_PATH) and (root / STATE_PATH).is_dir()
            else []
        )
    )
    receipt = StepReceipt(
        step_id=INDEX_STEP_ID,
        tool_id="graphify",
        status=OperationStatus.FAILED,
        message="Graphify indexing began but did not complete.",
        timestamp=_now(),
        owned_paths=owned,
    )
    _record_step(record, receipt)
    _persist(record, project_root=str(root))
    check = None
    try:
        if not owned:
            directories(root, ".stackwinnow")
            (root / STATE_PATH).mkdir(mode=0o700)
            owned.append(STATE_PATH)
            receipt.owned_paths[:] = owned
            _persist(record, project_root=str(root))
        directories(root, STATE_PATH)
        generation = f"{STATE_PATH}/run-{uuid4().hex}"
        (root / generation).mkdir(mode=0o700)
        source = root / generation / "source"
        source.mkdir(mode=0o700)
        for item in plan.sources:
            raw = _read_at(root, item.path)
            if _digest(raw) != item.sha256:
                raise GraphifyError("Source changed while staging the reviewed input.")
            target = source / item.path
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(raw)
        directories(root, f"{STATE_PATH}/home", create=True)
        for name in (".config", ".cache"):
            directories(root, f"{STATE_PATH}/home/{name}", create=True)
        command = index_command(root, root / ENV_PATH / "bin/python")
        argv = list(command.argv)
        argv[argv.index("extract") + 1] = str(source)
        argv.insert(1, "-B")
        output = root / generation / "output"
        argv[argv.index("--out") + 1] = str(output)
        result = runner(
            argv, cwd=command.cwd, timeout=command.timeout_seconds, extra_env=command.environment
        )
        if not result.succeeded:
            raise GraphifyError("Graphify extraction failed or timed out.")
        graph_relative = f"{generation}/output/graphify-out/graph.json"
        raw = _read_at(root, graph_relative)
        check = check_relationship(_json(raw), plan.expectation)
        if check.status != OperationStatus.SUCCEEDED:
            raise GraphifyError(check.message)
        query = relationship_query(root, root / ENV_PATH / "bin/python", check)
        query_argv = list(query.argv)
        query_argv.insert(1, "-B")
        query_argv[query_argv.index("--graph") + 1] = str(root / graph_relative)
        outcome = runner(
            query_argv, cwd=query.cwd, timeout=query.timeout_seconds, extra_env=query.environment
        )
        if not outcome.succeeded:
            raise GraphifyError("Graphify relationship query failed or timed out.")
        _, installation = validate_graphify_installation(root, plan.installation_plan)
        if installation != plan.installation_sha256 or snapshot_sources(root) != plan.sources:
            raise GraphifyError("Runtime or sources changed during extraction; review a new plan.")
        # Never silently overwrite an externally changed graph while extraction ran.
        if (
            _optional_digest(root, PROVENANCE_PATH) != plan.previous_provenance_sha256
            or _optional_digest(root, GRAPH_PATH) != plan.previous_graph_sha256
        ):
            raise GraphifyError("Index state changed during extraction; inspect it.")
        directories(root, f"{INDEX_PATH}/graphify-out", create=True)
        provenance = GraphifyProvenance(plan=plan, graph_sha256=_digest(raw))
        proof = provenance.model_dump_json(indent=2).encode()
        _publish(root, GRAPH_PATH, raw)
        _publish(root, PROVENANCE_PATH, proof)
        receipt = receipt.model_copy(
            update={
                "status": OperationStatus.SUCCEEDED,
                "message": "Fresh staged Graphify extraction and upstream relationship query passed.",
                "owned_paths": owned,
                "evidence": [
                    EvidenceRef(source=GRAPH_PATH, detail=f"sha256:{_digest(raw)}"),
                    EvidenceRef(source=PROVENANCE_PATH, detail=f"sha256:{_digest(proof)}"),
                ],
            }
        )
    except (OSError, ValueError, RuntimeError, RecursionError) as exc:
        receipt = receipt.model_copy(
            update={
                "owned_paths": owned,
                "message": f"Graphify indexing failed ({type(exc).__name__}); inspect retained state before retrying.",
            }
        )
    _record_step(record, receipt)
    _persist(record, project_root=str(root))
    return GraphifyIndexResult(
        dry_run=False,
        indexed=receipt.status == OperationStatus.SUCCEEDED,
        relationship_check=check,
        record=record,
        results=[
            OperationResult(
                status=receipt.status,
                message=receipt.message,
                step_id=INDEX_STEP_ID,
                tool_id="graphify",
                evidence=receipt.evidence,
            )
        ],
    )


def apply_graphify_index(
    plan: GraphifyIndexPlan | GraphifyExecutionPlan,
    *,
    dry_run: bool = False,
    command_runner: CommandRunner = run_command,
    before_execute: Callable[[], None] | None = None,
) -> GraphifyIndexResult:
    """Apply a reviewed index plan under the shared lock; repeat only fresh success."""
    try:
        if isinstance(plan, GraphifyExecutionPlan):
            # Original preparation remains a compatibility entry point only when
            # its exact immutable install recipe and reviewed sources still match.
            original, _ = validate_graphify_installation(_root(plan.project_root), plan)
            if original != GraphifyExecutionPlan.model_validate(plan.model_dump()):
                raise GraphifyError("Execution preparation does not match the installed recipe.")
            if any(
                _digest(_read_at(Path(plan.project_root), item.path)) != item.sha256
                for item in plan.sources
            ):
                raise GraphifyError("Sources changed; generate a separate index plan.")
            plan = plan_graphify_index(
                plan.project_root, expectation=plan.expectation, installation_plan=plan
            )
        plan = GraphifyIndexPlan.model_validate(plan.model_dump())
        root = _root(plan.project_root)
        if dry_run:
            reused = _validate(plan)
            return GraphifyIndexResult(
                dry_run=True,
                indexed=reused,
                record=record_for(root),
                results=[
                    OperationResult(
                        status=OperationStatus.SKIPPED,
                        message="Dry run: validate and stage fresh indexing; no files changed.",
                        tool_id="graphify",
                        step_id=INDEX_STEP_ID,
                    )
                ],
            )
        with project_lock(str(root)):
            if before_execute is not None:
                before_execute()
            if _validate(plan):
                _, check = inspect_graphify_index(root)
                return GraphifyIndexResult(
                    dry_run=False,
                    indexed=True,
                    relationship_check=check,
                    record=record_for(root),
                    results=[
                        OperationResult(
                            status=OperationStatus.SKIPPED,
                            message="The saved index plan remains current; reused verified graph evidence.",
                            tool_id="graphify",
                            step_id=INDEX_STEP_ID,
                        )
                    ],
                )
            return _execute(root, plan, command_runner, record_for(root))
    except GraphifyError:
        raise
    except (OSError, ValueError, RuntimeError, InstallerError, ProjectLockError) as exc:
        raise GraphifyError(
            "Cannot index Graphify; inspect plan, runtime and owned state."
        ) from exc

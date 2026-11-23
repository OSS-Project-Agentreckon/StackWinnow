"""Bounded read-only state bindings and explicitly permitted receipt transitions."""

import os
import platform
import shutil
import sys
from pathlib import Path

from pydantic import Field

from stackwinnow.adapters._managed import record_for
from stackwinnow.adapters.graphify_plan import _digest, _read_at
from stackwinnow.contracts import Contract
from stackwinnow.installer import ExecutionRecord


class WorkflowError(ValueError):
    """The workflow requires a new review or an explicit recovery action."""


class ExecutableIdentity(Contract):
    path: str
    identity: tuple[int, int, int, int, int]


class WorkflowState(Contract):
    root_identity: tuple[int, int]
    host: tuple[str, str, str, str, str]
    executables: dict[str, ExecutableIdentity | None]
    inputs: dict[str, str | None]
    configurations: dict[str, str | None]
    sources: dict[str, str] | None
    record: ExecutionRecord
    graph_artifacts: dict[str, str | None] = Field(default_factory=dict)


def digest_at(root: Path, relative: str) -> str | None:
    try:
        return _digest(_read_at(root, relative))
    except FileNotFoundError:
        return None


def executable_identities(tool_ids: list[str]) -> dict[str, ExecutableIdentity | None]:
    names = {"python"}
    if set(tool_ids) & {"promptfoo", "playwright-mcp"}:
        names.update(("node", "npm"))
    if set(tool_ids) & {"graphify", "playwright-mcp"}:
        names.add("codex")
    found = {}
    for name in sorted(names):
        candidate = sys.executable if name == "python" else shutil.which(name)
        if candidate is None:
            found[name] = None
            continue
        path = Path(candidate).resolve(strict=True)
        info = path.stat()
        if not path.is_file() or not os.access(path, os.X_OK):
            raise WorkflowError(f"{name} must resolve to an executable regular file.")
        found[name] = ExecutableIdentity(
            path=str(path),
            identity=(info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns),
        )
    return found


def snapshot(root: Path, tool_ids: list[str]) -> WorkflowState:
    from stackwinnow.adapters.graphify_index import PROVENANCE_PATH, snapshot_sources
    from stackwinnow.adapters.graphify_plan import GRAPH_PATH

    info = root.stat()
    graphify = "graphify" in tool_ids
    return WorkflowState(
        root_identity=(info.st_dev, info.st_ino),
        host=(
            platform.system(),
            platform.machine(),
            platform.python_implementation(),
            platform.python_version(),
            platform.mac_ver()[0],
        ),
        executables=executable_identities(tool_ids),
        inputs={
            name: digest_at(root, name)
            for name in ("pyproject.toml", "package.json", "stackwinnow.json")
        },
        configurations={
            name: digest_at(root, name)
            for name in (".codex/config.toml", "promptfooconfig.stackwinnow.json")
        },
        sources={item.path: item.sha256 for item in snapshot_sources(root)} if graphify else None,
        record=record_for(root),
        graph_artifacts={name: digest_at(root, name) for name in (PROVENANCE_PATH, GRAPH_PATH)}
        if graphify
        else {},
    )


def validate_transition(
    before: ExecutionRecord,
    after: ExecutionRecord,
    tool_id: str,
    step_ids: set[str],
    no_op_steps: set[str] | None = None,
) -> ExecutionRecord:
    """Advance only from the adapter's returned record, preserving unrelated history."""
    after = ExecutionRecord.model_validate(after.model_dump())
    if before.model_dump(exclude={"steps"}) != after.model_dump(exclude={"steps"}):
        raise WorkflowError("Unrelated receipt history changed during the workflow.")
    old = {s.step_id: s for s in before.steps if s.step_id not in step_ids}
    new = {s.step_id: s for s in after.steps if s.step_id not in step_ids}
    if old != new or len({s.step_id for s in after.steps}) != len(after.steps):
        raise WorkflowError("An unrelated receipt changed during a workflow phase.")
    if any(s.tool_id != tool_id for s in after.steps if s.step_id in step_ids):
        raise WorkflowError("The phase returned ownership for another tool.")
    for step_id in step_ids:
        if after.is_succeeded(step_id, tool_id):
            continue
        receipt = after.receipt_for(step_id)
        if (
            step_id in (no_op_steps or set())
            and receipt is not None
            and receipt.status == "skipped"
            and not receipt.dry_run
            and not receipt.owned_paths
            and not receipt.configuration_ownership
            and receipt.configuration_intents
            and all(
                not p.edits and p.expected_file == p.written_file
                for p in receipt.configuration_intents
            )
        ):
            continue
        raise WorkflowError(
            "The phase did not return successful steps or a reviewed configuration no-op."
        )
    return after


def validate_verification_transition(
    before: ExecutionRecord, after: ExecutionRecord, report, *, provenance_sha256: str | None = None
) -> None:
    """Protect setup ownership while permitting only the reported verifier receipts."""
    import re

    if before.model_dump(exclude={"steps"}) != after.model_dump(exclude={"steps"}):
        raise WorkflowError("Ownership history changed during verification.")
    patterns = {
        "headroom": r"headroom-[a-f0-9]{32}-verify",
        "promptfoo": r"promptfoo-[a-f0-9]{32}-evaluate",
        "graphify": r"graphify-client-[a-f0-9]{32}",
    }
    evidence = {
        tool.tool_id: {
            item.source
            for check in tool.checks
            if check.kind == "functional"
            for item in check.evidence
        }
        for tool in report.tools
    }
    prior = {row.step_id: row for row in before.steps}
    final = {row.step_id: row for row in after.steps}
    if len(final) != len(after.steps) or not prior.keys() <= final.keys():
        raise WorkflowError("Existing ownership receipts disappeared during verification.")
    for step_id, receipt in final.items():
        if step_id in prior and receipt == prior[step_id]:
            continue
        if step_id in prior:
            raise WorkflowError("Existing setup ownership changed during verification.")
        pattern = patterns.get(receipt.tool_id)
        if (
            pattern is None
            or re.fullmatch(pattern, step_id) is None
            or receipt.configuration_ownership
            or receipt.configuration_intents
            or receipt.dry_run
            or receipt.status != "succeeded"
            or not {item.source for item in receipt.evidence} & evidence.get(receipt.tool_id, set())
        ):
            raise WorkflowError("Unexpected receipt changes during verification.")
        # Verification owns evidence files only, never a runtime or configuration.
        for path in receipt.owned_paths:
            absolute = Path(path) if Path(path).is_absolute() else Path(after.project_root) / path
            if not any(
                absolute
                == (
                    Path(source)
                    if Path(source).is_absolute()
                    else Path(after.project_root) / source
                )
                for source in evidence[receipt.tool_id]
            ):
                raise WorkflowError("Verification claimed an unreported owned path.")

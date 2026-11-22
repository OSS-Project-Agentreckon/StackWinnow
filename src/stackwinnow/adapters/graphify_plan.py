"""Read-only, reproducible preparation for Graphify managed execution.

Full install/index execution remains pending; the install-only adapter accepts
an explicit subset. Validation binds the recipe to current inputs, not approval.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import stat
import sys
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal
from urllib.parse import urlsplit

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.tags import compatible_tags, cpython_tags, mac_platforms
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version
from pydantic import Field, ValidationError, model_validator

from stackwinnow.adapters.graphify import (
    GRAPH_PATH,
    STATE_PATH,
    VERSION,
    WHEEL_SHA256,
    WHEEL_URL,
    GraphifyError,
    RelationshipExpectation,
    _root,
)
from stackwinnow.catalog import CatalogError, load_catalog
from stackwinnow.contracts import Contract, UntrimmedText
from stackwinnow.installer import ExecutionRecord

LOCK_SHA256 = "94f289eded6c09af11187d14f70aa9e945e153c164aba9dc947a024dbb6b2c20"
MAX_INPUT_BYTES = 4 * 1024 * 1024
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
ENV_PATH = ".stackwinnow/envs/graphify/python"


class LockedWheel(Contract):
    name: str
    version: str
    url: str
    sha256: Digest
    requires_python: str
    requires_dist: tuple[str, ...]


class GraphifyLock(Contract):
    schema_version: Literal[1] = 1
    target: Literal["cpython311-macos14-arm64"]
    packages: tuple[LockedWheel, ...]

    @model_validator(mode="after")
    def complete_dependencies(self) -> GraphifyLock:
        names = [canonicalize_name(item.name) for item in self.packages]
        if len(names) != len(set(names)) or not names:
            raise ValueError("Locked distributions must be unique and nonempty.")
        by_name = dict(zip(names, self.packages, strict=True))
        platforms = list(mac_platforms(version=(14, 0), arch="arm64"))
        tags = set(cpython_tags((3, 11), platforms=platforms))
        tags.update(compatible_tags((3, 11), interpreter="cp311", platforms=platforms))
        environment = default_environment()
        environment.update(
            python_version="3.11",
            python_full_version="3.11.14",
            implementation_name="cpython",
            implementation_version="3.11.14",
            platform_python_implementation="CPython",
            sys_platform="darwin",
            os_name="posix",
            platform_system="Darwin",
            platform_machine="arm64",
            platform_release="23.0.0",
            platform_version="",
            extra="",
        )
        for item in self.packages:
            url = urlsplit(item.url)
            if (
                url.scheme != "https"
                or url.netloc != "files.pythonhosted.org"
                or url.query
                or url.fragment
            ):
                raise ValueError("Lock contains an unexpected artifact URL.")
            name, version, _, wheel_tags = parse_wheel_filename(PurePosixPath(url.path).name)
            if (
                name != canonicalize_name(item.name)
                or str(version) != item.version
                or not tags.intersection(wheel_tags)
            ):
                raise ValueError("Wheel identity or target is inconsistent.")
            if not SpecifierSet(item.requires_python).contains("3.11.14"):
                raise ValueError("Wheel does not support the locked Python target.")
            for value in item.requires_dist:
                requirement = Requirement(value)
                if requirement.marker and not requirement.marker.evaluate(environment):
                    continue
                dependency = by_name.get(canonicalize_name(requirement.name))
                if (
                    dependency is None
                    or requirement.url
                    or requirement.extras
                    or not requirement.specifier.contains(dependency.version)
                ):
                    raise ValueError("Lock is missing a compatible required dependency.")
        graphify = by_name.get("graphifyy")
        if graphify is None or (graphify.version, graphify.url, graphify.sha256) != (
            VERSION,
            WHEEL_URL,
            WHEEL_SHA256,
        ):
            raise ValueError("Lock must contain the reviewed Graphify wheel.")
        return self


class SourceSnapshot(Contract):
    path: UntrimmedText
    sha256: Digest


class RuntimeSnapshot(Contract):
    executable: UntrimmedText
    implementation: str
    version: str
    system: str
    machine: str
    macos_version: str


class GraphifyExecutionPlan(Contract):
    """Fresh-install preparation; no ownership, execution, or connectivity claim."""

    schema_version: Literal[1] = 1
    tool_id: Literal["graphify"] = "graphify"
    phase: Literal["execution-preparation"] = "execution-preparation"
    scope: Literal["local-install-index"] = "local-install-index"
    assistant: Literal["codex"] = "codex"
    project_root: UntrimmedText
    target: Literal["cpython311-macos14-arm64"] = "cpython311-macos14-arm64"
    runtime: RuntimeSnapshot
    lock_sha256: Digest
    packages: tuple[LockedWheel, ...]
    expectation: RelationshipExpectation
    sources: tuple[SourceSnapshot, ...]
    receipts_sha256: Digest | None
    environment_path: Literal[".stackwinnow/envs/graphify/python"] = ENV_PATH
    graph_path: Literal[".stackwinnow/graphify/index/graphify-out/graph.json"] = GRAPH_PATH
    operations: tuple[str, ...]
    network_required: Literal[True] = True
    ready_to_apply: Literal[False] = False
    blockers: tuple[str, ...]


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_at(root: Path, relative: str, *, limit: int = MAX_INPUT_BYTES) -> bytes:
    """Bounded reads through anchored, no-follow directory descriptors."""
    if not all(hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")):
        raise GraphifyError("Graphify plan input inspection requires a POSIX filesystem API.")
    path = PurePosixPath(relative)
    if (
        path.is_absolute()
        or not path.parts
        or ".." in path.parts
        or path.as_posix() != relative
        or "\\" in relative
        or "\x00" in relative
    ):
        raise GraphifyError("Use a normalized project-relative input path.")
    descriptors = []
    try:
        descriptors.append(os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
        for component in path.parts[:-1]:
            descriptors.append(
                os.open(
                    component,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptors[-1],
                )
            )
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptors[-1])
        # Keep descriptor ownership here even if constructing the stream fails.
        descriptors.append(fd)
        with os.fdopen(fd, "rb", closefd=False) as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise GraphifyError("Plan inputs must be bounded regular files.")
            data = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
            if len(data) > limit or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise GraphifyError("An input changed while preparing the plan; retry.")
            return data
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = item
    return value


def _json(data: bytes):
    return json.loads(data, object_pairs_hook=_unique_object)


def load_graphify_lock() -> GraphifyLock:
    try:
        data = files("stackwinnow").joinpath("data/graphify-lock.json").read_bytes()
        if _digest(data) != LOCK_SHA256:
            raise GraphifyError("The bundled Graphify dependency lock has changed.")
        return GraphifyLock.model_validate(_json(data))
    except (OSError, ValueError) as exc:
        raise GraphifyError("Cannot validate the bundled Graphify dependency lock.") from exc


def load_relationship_expectation(path: str | Path) -> RelationshipExpectation:
    try:
        selected = Path(path).absolute()
        return RelationshipExpectation.model_validate(
            _json(_read_at(selected.parent, selected.name, limit=65536))
        )
    except (OSError, ValueError, RuntimeError) as exc:
        raise GraphifyError("Supply a valid, bounded relationship expectation JSON file.") from exc


def graphify_requirements() -> str:
    """Hash-enforced wheel inputs for the locked target; generating text is offline."""
    return (
        "\n".join(
            f"{wheel.name} @ {wheel.url} --hash=sha256:{wheel.sha256}"
            for wheel in load_graphify_lock().packages
        )
        + "\n"
    )


def _runtime() -> RuntimeSnapshot:
    return RuntimeSnapshot(
        executable=os.path.abspath(sys.executable),
        implementation=platform.python_implementation(),
        version=platform.python_version(),
        system=platform.system(),
        machine=platform.machine(),
        macos_version=platform.mac_ver()[0],
    )


def plan_graphify_execution(
    project_root: str | Path,
    *,
    expectation: RelationshipExpectation,
) -> GraphifyExecutionPlan:
    """Prepare a fresh-install plan without commands, network or writes.

    Snapshots cover the explicit relationship's source files, not the whole
    project. A future executor must additionally establish index provenance.
    """
    return _prepare_graphify_execution(project_root, expectation=expectation, require_fresh=True)


def _prepare_graphify_execution(
    project_root: str | Path,
    *,
    expectation: RelationshipExpectation,
    require_fresh: bool,
) -> GraphifyExecutionPlan:
    """Rebuild recipe inputs; the install adapter separately validates existing ownership."""
    try:
        root = _root(project_root)
        expected = RelationshipExpectation.model_validate(expectation.model_dump())
        entry = load_catalog().get("graphify")
        if (
            entry.license_review != "reviewed"
            or entry.license != "Apache-2.0"
            or str(entry.repository).rstrip("/") != "https://github.com/Graphify-Labs/graphify"
        ):
            raise GraphifyError("Graphify's reviewed catalog identity/license is unavailable.")
        lock = load_graphify_lock()
        # Occupied locations need the pending shared reconciliation interface.
        if require_fresh and (
            os.path.lexists(root / ".stackwinnow/envs/graphify")
            or os.path.lexists(root / STATE_PATH)
        ):
            raise GraphifyError("Existing Graphify paths require reconciliation before planning.")
        receipt_data = None
        try:
            receipt_data = _read_at(root, ".stackwinnow/receipts.json")
        except FileNotFoundError:
            pass
        if receipt_data is not None:
            record = ExecutionRecord.model_validate(_json(receipt_data))
            ids = [step.step_id for step in record.steps]
            if record.project_root != str(root) or len(ids) != len(set(ids)):
                raise GraphifyError("Receipt ownership is invalid or ambiguous.")
            if require_fresh and any(
                step.tool_id == "graphify" and not step.dry_run for step in record.steps
            ):
                raise GraphifyError(
                    "Existing Graphify receipts require reconciliation before planning."
                )
        sources = tuple(
            SourceSnapshot(path=path, sha256=_digest(_read_at(root, path)))
            for path in sorted({expected.caller_file, expected.callee_file})
        )
        runtime = _runtime()
        blockers = [
            "A complete dependency-license audit remains pending; wheels are downloaded, not redistributed.",
            "Owned Codex configuration and actual client verification are not implemented.",
        ]
        if (
            runtime.implementation != "CPython"
            or runtime.system != "Darwin"
            or runtime.machine != "arm64"
            or not runtime.macos_version
            or Version(runtime.macos_version) < Version("14")
            or not SpecifierSet(">=3.11.5,<3.12").contains(runtime.version)
        ):
            blockers.append("This lock requires CPython 3.11.5+ (3.11 only), macOS 14+ and arm64.")
        if not SpecifierSet(">=3.11.5,<3.12").contains(runtime.version) or any(
            not SpecifierSet(wheel.requires_python).contains(runtime.version)
            for wheel in lock.packages
        ):
            blockers.append(
                "The current Python version does not satisfy the locked dependency target."
            )
        return GraphifyExecutionPlan(
            project_root=str(root),
            runtime=runtime,
            lock_sha256=LOCK_SHA256,
            packages=lock.packages,
            expectation=expected,
            sources=sources,
            receipts_sha256=None if receipt_data is None else _digest(receipt_data),
            operations=(
                "create-environment",
                "install-locked-wheels",
                "index-code",
                "query-relationship",
            ),
            blockers=tuple(blockers),
        )
    except GraphifyError:
        raise
    except (OSError, ValueError, RuntimeError, KeyError, CatalogError) as exc:
        raise GraphifyError(
            "Cannot prepare Graphify execution; check project inputs and receipts."
        ) from exc


def validate_graphify_execution_plan(plan: GraphifyExecutionPlan) -> GraphifyExecutionPlan:
    """Reject modified recipe fields or changed inputs; never authorize execution."""
    try:
        checked = GraphifyExecutionPlan.model_validate(plan.model_dump())
        current = plan_graphify_execution(checked.project_root, expectation=checked.expectation)
        if checked != current:
            raise GraphifyError(
                "Graphify plan or its inputs changed; generate and review a new plan."
            )
        return checked
    except ValidationError as exc:
        raise GraphifyError("Invalid Graphify execution plan; generate a new plan.") from exc


def load_graphify_execution_plan(path: str | Path) -> GraphifyExecutionPlan:
    try:
        selected = Path(path).absolute()
        plan = GraphifyExecutionPlan.model_validate(
            _json(_read_at(selected.parent, selected.name, limit=1024 * 1024))
        )
        return validate_graphify_execution_plan(plan)
    except (OSError, ValueError, RuntimeError) as exc:
        raise GraphifyError(
            "Invalid or stale Graphify plan; generate and review a new plan."
        ) from exc

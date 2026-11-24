"""Bounded, offline inspection of declared project metadata and explicit intent."""

from __future__ import annotations

import json
import math
import os
import re
import stat
import tomllib
from pathlib import Path, PurePosixPath
from typing import Literal

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from pydantic import Field

from stackwinnow.catalog import Catalog, load_catalog
from stackwinnow.contracts import (
    Contract,
    EvidenceRef,
    Identifier,
    OperationResult,
    OperationStatus,
    ProjectProfile,
)

MAX_MANIFEST_BYTES = 1024 * 1024
ModelPreference = Literal["local", "hosted", "any"]
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_NPM_NAME = re.compile(r"(?:@[A-Za-z0-9._-]+/)?[A-Za-z0-9][A-Za-z0-9._-]*")
_RANGE = re.compile(r"[0-9xXvV.*+~^<>=|!(), -]{1,256}")


class InspectionError(ValueError):
    """Invalid project path, selected config path, or explicit tool choice."""


class InspectionResult(Contract):
    schema_version: Literal[1] = 1
    profile: ProjectProfile
    selected_tools: list[Identifier] = Field(default_factory=list)
    model_preference: ModelPreference | None = None
    diagnostics: list[OperationResult] = Field(default_factory=list)

    @property
    def complete(self) -> bool:
        return all(
            item.status not in (OperationStatus.FAILED, OperationStatus.BLOCKED)
            for item in self.diagnostics
        )


class _ReadError(ValueError):
    pass


def _config_path(path: str) -> str:
    relative = PurePosixPath(path)
    if (
        not relative.parts
        or relative.is_absolute()
        or ".." in relative.parts
        or "\\" in path
        or not path.isprintable()
        or relative.as_posix() != path
        or relative.suffix.lower() != ".json"
    ):
        raise InspectionError("--config must be a normalized project-relative .json path.")
    return path


def _read(root: Path, relative: str) -> bytes:
    """Read real files through directory descriptors; never follow child symlinks."""
    if os.name != "posix":
        raise _ReadError("Project file inspection currently supports macOS and Linux.")
    descriptors: list[int] = []
    try:
        directories = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            descriptors.append(os.open(root, directories))
        except FileNotFoundError as exc:
            raise _ReadError(
                "Project directory disappeared; inspect an existing project again."
            ) from exc
        parts = PurePosixPath(relative).parts
        for part in parts[:-1]:
            descriptors.append(os.open(part, directories, dir_fd=descriptors[-1]))
        descriptor = os.open(
            parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=descriptors[-1],
        )
        descriptors.append(descriptor)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise _ReadError(
                "Use a regular file with one hard link; linked/special files are skipped."
            )
        if before.st_size > MAX_MANIFEST_BYTES:
            raise _ReadError("File exceeds the 1 MiB inspection limit.")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(MAX_MANIFEST_BYTES + 1)
        after = os.fstat(descriptor)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise _ReadError("File exceeds the 1 MiB inspection limit.")
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise _ReadError("File changed while being read; inspect again.")
        return raw
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _diagnostic(result: InspectionResult, source: str, message: str, status: str) -> None:
    result.diagnostics.append(OperationResult(status=status, message=f"{source}: {message}"))


def _fact(result: InspectionResult, source: str, key: str, values: list[str], field: str) -> None:
    result.profile.facts[key] = sorted(set(result.profile.facts.get(key, []) + values))
    result.profile.evidence.append(EvidenceRef(source=source, detail=f"{field} declares {key}."))


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON keys")
        value[key] = item
    return value


def _bad_constant(value: str) -> None:
    raise ValueError("Non-finite JSON number")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("Non-finite JSON number")
    return parsed


def _json(raw: bytes) -> dict[str, object]:
    value = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_pairs,
        parse_constant=_bad_constant,
        parse_float=_finite_float,
    )
    if not isinstance(value, dict):
        raise ValueError("Expected JSON object")
    return value


def _python_dependencies(
    result: InspectionResult, source: str, field: str, key: str, value: object
) -> None:
    if not isinstance(value, list):
        _diagnostic(result, source, f"{field} must be an array of dependency strings.", "failed")
        return
    names = []
    invalid = False
    for item in value:
        try:
            if not isinstance(item, str):
                raise InvalidRequirement("Not a string")
            names.append(canonicalize_name(Requirement(item).name))
        except (InvalidRequirement, RecursionError):
            # Deeply nested markers can exceed the parser's recursion limit.
            # Reject only this declaration so the remaining findings survive.
            invalid = True
    if names or not value:
        _fact(result, source, key, names, field)
    if invalid:
        _diagnostic(
            result,
            source,
            f"{field} contains invalid or overly complex dependencies; valid names retained.",
            "failed",
        )


def _python(result: InspectionResult, source: str, document: dict[str, object]) -> None:
    project = document.get("project")
    if project is None:
        _diagnostic(
            result,
            source,
            "No [project] metadata; tool-specific formats are not interpreted.",
            "skipped",
        )
        return
    if not isinstance(project, dict):
        _diagnostic(result, source, "[project] must be a table.", "failed")
        return
    dynamic = project.get("dynamic", [])
    dynamic_fields: set[str] = set()
    if not isinstance(dynamic, list) or any(not isinstance(item, str) for item in dynamic):
        _diagnostic(result, source, "project.dynamic must be an array of field names.", "failed")
    else:
        dynamic_fields = set(dynamic)
        if dynamic_fields:
            _diagnostic(
                result,
                source,
                "Dynamic project fields are not evaluated; their values remain unknown.",
                "skipped",
            )
    for field in ("dependencies", "optional-dependencies", "requires-python"):
        if field in dynamic_fields and field in project:
            _diagnostic(
                result,
                source,
                f"project.{field} is both static and dynamic; value is unknown.",
                "failed",
            )
    if "dependencies" in project and "dependencies" not in dynamic_fields:
        _python_dependencies(
            result, source, "project.dependencies", "python.dependencies", project["dependencies"]
        )
    if "optional-dependencies" in project and "optional-dependencies" not in dynamic_fields:
        groups = project["optional-dependencies"]
        if not isinstance(groups, dict):
            _diagnostic(result, source, "project.optional-dependencies must be a table.", "failed")
        else:
            for group, values in sorted(groups.items()):
                if not _NAME.fullmatch(group):
                    _diagnostic(
                        result,
                        source,
                        "Unsupported optional dependency group name; skipped.",
                        "failed",
                    )
                    continue
                _python_dependencies(
                    result,
                    source,
                    f"project.optional-dependencies.{group}",
                    f"python.optional_dependencies.{group}",
                    values,
                )
    if "requires-python" in project and "requires-python" not in dynamic_fields:
        constraint = project["requires-python"]
        try:
            if not isinstance(constraint, str) or len(constraint) > 256:
                raise InvalidSpecifier("Unsupported constraint")
            specifiers = SpecifierSet(constraint)
            # Arbitrary equality accepts non-version strings; do not emit those.
            for specifier in specifiers:
                if specifier.operator == "===":
                    Version(specifier.version)
            normalized = str(specifiers)
            if not normalized:
                raise InvalidSpecifier("Empty constraint")
            _fact(result, source, "python.requires", [normalized], "project.requires-python")
        except (InvalidSpecifier, InvalidVersion):
            _diagnostic(
                result,
                source,
                "project.requires-python must be a supported PEP 440 version constraint.",
                "failed",
            )


def _requirements_txt(result: InspectionResult, source: str, raw: bytes) -> None:
    """Parse a requirements.txt file and record python dependencies."""
    names = []
    invalid = False
    for raw_line in raw.decode("utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        try:
            names.append(canonicalize_name(Requirement(line).name))
        except (InvalidRequirement, RecursionError):
            invalid = True
    if names:
        _fact(result, source, "python.dependencies", names, "dependencies")
        _fact(result, source, "manifests", [source], "Manifest")
        _fact(result, source, "ecosystems", ["python"], "Manifest")
    if invalid:
        _diagnostic(
            result,
            source,
            "Some requirements.txt entries could not be parsed; valid names retained.",
            "failed",
        )
    if names and not invalid:
        _diagnostic(
            result,
            source,
            "Read declared metadata; no installed or functional state was checked.",
            "succeeded",
        )


def _node(result: InspectionResult, source: str, document: dict[str, object]) -> None:
    for group in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        if group not in document:
            continue
        values = document[group]
        if not isinstance(values, dict):
            _diagnostic(
                result, source, f"{group} must be an object of dependency declarations.", "failed"
            )
            continue
        names = [
            name
            for name, value in values.items()
            if len(name) <= 214 and _NPM_NAME.fullmatch(name) and isinstance(value, str)
        ]
        if names or not values:
            _fact(result, source, f"node.{group}", names, group)
        if len(names) != len(values):
            _diagnostic(
                result,
                source,
                f"{group} contains invalid declarations; valid names retained.",
                "failed",
            )
    if "engines" in document:
        engines = document["engines"]
        if not isinstance(engines, dict):
            _diagnostic(result, source, "engines must be an object.", "failed")
        elif "node" in engines:
            constraint = engines["node"]
            if isinstance(constraint, str) and constraint.strip() and _RANGE.fullmatch(constraint):
                _fact(result, source, "node.requires", [constraint.strip()], "engines.node")
            else:
                _diagnostic(
                    result,
                    source,
                    "engines.node must be a supported numeric version expression.",
                    "failed",
                )
    if "workspaces" in document:
        _diagnostic(
            result,
            source,
            "Workspace packages are not scanned; only root declarations are reported.",
            "skipped",
        )


def _config(result: InspectionResult, source: str, document: dict[str, object]) -> None:
    if "mcpServers" not in document:
        _diagnostic(
            result,
            source,
            "No mcpServers object; other configuration formats are not interpreted.",
            "skipped",
        )
        return
    servers = document["mcpServers"]
    if not isinstance(servers, dict):
        _diagnostic(result, source, "mcpServers must be an object.", "failed")
        return
    names = [
        name
        for name, value in servers.items()
        if name
        and name == name.strip()
        and len(name) <= 128
        and name.isprintable()
        and isinstance(value, dict)
    ]
    if names or not servers:
        _fact(result, source, "config.mcp_servers", names, "mcpServers keys")
    if len(names) != len(servers):
        _diagnostic(
            result,
            source,
            "Some server registrations have invalid names or non-object values; skipped.",
            "failed",
        )


def inspect_project(
    project_root: Path | str,
    *,
    goals: list[str] | None = None,
    assistant: str | None = None,
    selected_tools: list[str] | None = None,
    model_preference: ModelPreference | None = None,
    config_path: str | None = None,
    catalog: Catalog | None = None,
) -> InspectionResult:
    """Read project declarations. Invalid requests raise; file problems become diagnostics."""
    try:
        root = Path(project_root).resolve(strict=True)
        if not root.is_dir():
            raise InspectionError("Project root must be an existing readable directory.")
    except (OSError, RuntimeError, ValueError) as exc:
        raise InspectionError("Project root must be an existing readable directory.") from exc
    if config_path is not None:
        _config_path(config_path)
    result = InspectionResult(
        profile=ProjectProfile(project_root=str(root), goals=goals or [], assistant=assistant),
        selected_tools=list(dict.fromkeys(selected_tools or [])),
        model_preference=model_preference,
    )
    if result.selected_tools:
        catalog = catalog if catalog is not None else load_catalog()
        try:
            for tool_id in result.selected_tools:
                catalog.get(tool_id)
        except KeyError as exc:
            raise InspectionError(
                "Unknown tool ID; use 'stackwinnow catalog list' to see valid choices."
            ) from exc
    inputs = [("pyproject.toml", "python"), ("package.json", "node"), ("requirements.txt", "requirements")]
    if config_path is not None:
        inputs.append((config_path, "config"))
    for source, kind in inputs:
        try:
            raw = _read(root, source)
        except FileNotFoundError:
            _diagnostic(
                result, source, "File not found.", "failed" if kind == "config" else "skipped"
            )
            continue
        except _ReadError as exc:
            _diagnostic(result, source, str(exc), "blocked")
            continue
        except OSError:
            _diagnostic(
                result,
                source,
                "Cannot read file; check permissions and use real directories/files, not symlinks.",
                "blocked",
            )
            continue
        if kind == "requirements":
            _requirements_txt(result, source, raw)
            continue
        try:
            document = tomllib.loads(raw.decode("utf-8")) if kind == "python" else _json(raw)
        except (ValueError, UnicodeError, RecursionError):
            _diagnostic(
                result,
                source,
                "Invalid UTF-8 TOML."
                if kind == "python"
                else "Invalid UTF-8 JSON object; remove duplicate keys, comments, or non-finite numbers.",
                "failed",
            )
            continue
        if kind != "config":
            _fact(result, source, "manifests", [source], "Manifest")
            _fact(result, source, "ecosystems", [kind], "Manifest")
        start = len(result.diagnostics)
        {"python": _python, "node": _node, "config": _config}[kind](result, source, document)
        if len(result.diagnostics) == start:
            _diagnostic(
                result,
                source,
                "Read declared metadata; no installed or functional state was checked.",
                "succeeded",
            )
    return result

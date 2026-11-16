"""Read-only inspection of the host environment and installed prerequisites.

Importing or calling any function here never installs software, modifies
configuration, or writes files.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

from stackwinnow.contracts import EvidenceRef, OperationResult, OperationStatus, ProjectProfile

_MIN_PYTHON: tuple[int, int] = (3, 11)
_MIN_NODE_MAJOR: int = 18

_KNOWN_PACKAGE_MANAGERS: tuple[str, ...] = ("uv", "pip", "pip3", "npm", "brew", "apt", "apt-get")

# Maps executable name → assistant identifier (must satisfy Identifier pattern)
_ASSISTANT_EXECUTABLES: dict[str, str] = {
    "claude": "claude-code",
    "cursor": "cursor",
    "aider": "aider",
}


def _run_version(cmd: list[str]) -> str | None:
    """Return stripped stdout of a short-lived command, or None on any failure."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
        return proc.stdout.strip() if proc.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _check_python() -> tuple[str, OperationResult]:
    """Return (version_string, result). Never fails on a supported interpreter."""
    vi = sys.version_info
    version = f"{vi[0]}.{vi[1]}.{vi[2]}"
    required = f"{_MIN_PYTHON[0]}.{_MIN_PYTHON[1]}"
    if vi[:2] < _MIN_PYTHON:
        return version, OperationResult(
            status=OperationStatus.FAILED,
            message=f"Python {required}+ required — found {version} at {sys.executable}",
            errors=[f"Upgrade Python to {required} or later."],
        )
    return version, OperationResult(
        status=OperationStatus.SUCCEEDED,
        message=f"Python {version} at {sys.executable}",
        evidence=[EvidenceRef(source=sys.executable, detail=f"Python {version}")],
    )


def _check_node() -> tuple[str | None, OperationResult]:
    """Return (version_string_or_none, result)."""
    node_path = shutil.which("node")
    if not node_path:
        return None, OperationResult(
            status=OperationStatus.BLOCKED,
            message="Node.js not found — required for Graphify and Playwright MCP",
            errors=["Install Node.js 18 or later: https://nodejs.org"],
        )
    raw = _run_version(["node", "--version"])  # e.g. "v20.11.0"
    if raw is None:
        return None, OperationResult(
            status=OperationStatus.FAILED,
            message=f"Node.js found at {node_path} but version check failed",
            errors=["Run 'node --version' to investigate."],
        )
    version = raw.lstrip("v")
    try:
        major = int(version.split(".")[0])
    except ValueError:
        return None, OperationResult(
            status=OperationStatus.FAILED,
            message=f"Could not parse Node.js version: {raw!r}",
            errors=["Run 'node --version' to investigate."],
        )
    if major < _MIN_NODE_MAJOR:
        return version, OperationResult(
            status=OperationStatus.FAILED,
            message=f"Node.js {_MIN_NODE_MAJOR}+ required — found {version} at {node_path}",
            errors=[f"Upgrade Node.js to version {_MIN_NODE_MAJOR} or later."],
        )
    return version, OperationResult(
        status=OperationStatus.SUCCEEDED,
        message=f"Node.js {version} at {node_path}",
        evidence=[EvidenceRef(source=node_path, detail=f"Node.js {version}")],
    )


def _find_package_managers() -> list[str]:
    """Return names of supported package managers present on PATH."""
    return [pm for pm in _KNOWN_PACKAGE_MANAGERS if shutil.which(pm)]


def _detect_assistant() -> str | None:
    """Return an assistant identifier, or None if none is detected."""
    for exe, assistant_id in _ASSISTANT_EXECUTABLES.items():
        if shutil.which(exe):
            return assistant_id
    # Copilot does not expose a standalone executable; check VS Code extension dirs.
    extension_roots = [
        Path.home() / ".vscode" / "extensions",
        Path.home() / ".vscode-server" / "extensions",
    ]
    for root in extension_roots:
        if not root.is_dir():
            continue
        for entry in root.iterdir():
            if entry.name.lower().startswith("github.copilot"):
                return "github-copilot"
    return None


def inspect_environment(project_root: str) -> tuple[ProjectProfile, list[OperationResult]]:
    """Inspect the host environment. Read-only: never installs or modifies anything."""
    results: list[OperationResult] = []
    facts: dict[str, list[str]] = {}

    # OS
    os_name = platform.system()
    arch = platform.machine()
    os_detail = f"{os_name} {platform.release()} ({arch})"
    facts["os"] = [os_name]
    facts["architecture"] = [arch]
    results.append(
        OperationResult(
            status=OperationStatus.SUCCEEDED,
            message=f"OS: {os_detail}",
            evidence=[EvidenceRef(source="platform", detail=os_detail)],
        )
    )

    # Python
    py_version, py_result = _check_python()
    facts["python_version"] = [py_version]
    facts["python_path"] = [sys.executable]
    results.append(py_result)

    # Node
    node_version, node_result = _check_node()
    if node_version is not None:
        node_path = shutil.which("node")
        facts["node_version"] = [node_version]
        if node_path:
            facts["node_path"] = [node_path]
    results.append(node_result)

    # Package managers
    package_managers = _find_package_managers()
    if package_managers:
        facts["package_managers"] = package_managers
        results.append(
            OperationResult(
                status=OperationStatus.SUCCEEDED,
                message=f"Package managers: {', '.join(package_managers)}",
            )
        )
    else:
        results.append(
            OperationResult(
                status=OperationStatus.FAILED,
                message="No supported package managers found",
                errors=["Install pip, npm, or another supported package manager."],
            )
        )

    # AI assistant
    assistant = _detect_assistant()
    if assistant is not None:
        facts["assistant_detected"] = [assistant]

    profile = ProjectProfile(
        project_root=project_root,
        assistant=assistant,
        operating_system=os_detail,
        facts=facts,
    )
    return profile, results

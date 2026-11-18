"""Isolated Python and Node.js installation locations for managed tools.

Each tool gets its own subtree under .stackwinnow/envs/<tool_id>/ so
no two tools share packages and removal is scoped to one directory tree.
"""

from __future__ import annotations

import sys
from pathlib import Path

_MANAGED_ROOT = ".stackwinnow"
_ENVS_SUBDIR = "envs"
_PYTHON_SUBDIR = "python"
_NODE_SUBDIR = "node"


class EnvironmentBoundaryError(Exception):
    """Raised when a managed environment path would escape the project boundary."""


def _assert_safe_env_root(project_root: str) -> None:
    """Raise EnvironmentBoundaryError if the managed or envs directory is a symlink."""
    managed = Path(project_root) / _MANAGED_ROOT
    envs = managed / _ENVS_SUBDIR
    for candidate in (managed, envs):
        if candidate.is_symlink():
            raise EnvironmentBoundaryError(
                f"Managed directory '{candidate}' is a symlink; "
                "refusing to install outside the project boundary. "
                "Remove the symlink and retry."
            )


def _tool_env_root(project_root: str, tool_id: str) -> Path:
    _assert_safe_env_root(project_root)
    return Path(project_root) / _MANAGED_ROOT / _ENVS_SUBDIR / tool_id


def python_env_path(project_root: str, tool_id: str) -> Path:
    """Dedicated venv root for one tool. Each tool is fully isolated."""
    return _tool_env_root(project_root, tool_id) / _PYTHON_SUBDIR


def node_env_path(project_root: str, tool_id: str) -> Path:
    """Dedicated Node prefix root for one tool. Each tool is fully isolated."""
    return _tool_env_root(project_root, tool_id) / _NODE_SUBDIR


def python_executable(venv_path: Path) -> Path:
    """Path to the Python interpreter inside a venv."""
    if sys.platform == "win32":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def create_venv_args(venv_path: Path) -> list[str]:
    """Argument list to create an isolated Python venv at venv_path."""
    return [sys.executable, "-m", "venv", "--without-pip", str(venv_path)]


def bootstrap_pip_args(venv_path: Path) -> list[str]:
    """Argument list to install pip into a venv created without it."""
    return [str(python_executable(venv_path)), "-m", "ensurepip", "--upgrade"]


def pip_install_args(venv_path: Path, package: str, version: str) -> list[str]:
    """Argument list to pip-install a pinned package into an isolated venv.

    Uses 'python -m pip' rather than the pip script so this works correctly
    after a --without-pip venv + ensurepip bootstrap, where no unversioned
    pip script is guaranteed to exist.
    """
    return [
        str(python_executable(venv_path)),
        "-m",
        "pip",
        "install",
        "--quiet",
        f"{package}=={version}",
    ]


def npm_install_args(node_path: Path, package: str, version: str) -> list[str]:
    """Argument list to npm-install a pinned package into an isolated prefix."""
    return [
        "npm",
        "install",
        "--prefix",
        str(node_path),
        "--save=false",
        f"{package}@{version}",
    ]

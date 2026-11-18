"""Tests for isolated Python and Node.js environment paths.

These tests verify path structure and argument-list correctness only.
No venvs or node_modules are actually created.
"""

from __future__ import annotations

import sys
from pathlib import Path

from stackwinnow.environments import (
    _MANAGED_ROOT,
    bootstrap_pip_args,
    create_venv_args,
    node_env_path,
    npm_install_args,
    pip_install_args,
    python_env_path,
    python_executable,
)

# ---------------------------------------------------------------------------
# Path isolation
# ---------------------------------------------------------------------------


def test_python_env_is_under_managed_root(tmp_path: Path) -> None:
    path = python_env_path(str(tmp_path), "headroom")
    assert _MANAGED_ROOT in path.parts


def test_node_env_is_under_managed_root(tmp_path: Path) -> None:
    path = node_env_path(str(tmp_path), "graphify")
    assert _MANAGED_ROOT in path.parts


def test_different_tools_get_different_python_paths(tmp_path: Path) -> None:
    a = python_env_path(str(tmp_path), "headroom")
    b = python_env_path(str(tmp_path), "graphify")
    assert a != b


def test_different_tools_get_different_node_paths(tmp_path: Path) -> None:
    a = node_env_path(str(tmp_path), "headroom")
    b = node_env_path(str(tmp_path), "graphify")
    assert a != b


def test_same_tool_same_project_returns_same_python_path(tmp_path: Path) -> None:
    a = python_env_path(str(tmp_path), "headroom")
    b = python_env_path(str(tmp_path), "headroom")
    assert a == b


def test_different_projects_get_different_python_paths(tmp_path: Path) -> None:
    project_a = tmp_path / "project_a"
    project_b = tmp_path / "project_b"
    a = python_env_path(str(project_a), "headroom")
    b = python_env_path(str(project_b), "headroom")
    assert a != b


def test_python_env_path_contains_tool_id(tmp_path: Path) -> None:
    path = python_env_path(str(tmp_path), "headroom")
    assert "headroom" in str(path)


def test_node_env_path_contains_tool_id(tmp_path: Path) -> None:
    path = node_env_path(str(tmp_path), "graphify")
    assert "graphify" in str(path)


# ---------------------------------------------------------------------------
# Argument lists — no shell strings
# ---------------------------------------------------------------------------


def test_create_venv_args_uses_current_interpreter(tmp_path: Path) -> None:
    venv = tmp_path / "venv"
    args = create_venv_args(venv)
    assert args[0] == sys.executable
    assert str(venv) in args


def test_create_venv_args_is_a_list_of_strings(tmp_path: Path) -> None:
    args = create_venv_args(tmp_path / "venv")
    assert all(isinstance(a, str) for a in args)


def test_pip_install_args_pins_exact_version(tmp_path: Path) -> None:
    venv = tmp_path / "venv"
    args = pip_install_args(venv, "headroom", "0.4.1")
    combined = " ".join(args)
    assert "headroom==0.4.1" in combined


def test_pip_install_args_is_a_list_of_strings(tmp_path: Path) -> None:
    args = pip_install_args(tmp_path / "venv", "headroom", "0.4.1")
    assert all(isinstance(a, str) for a in args)


def test_npm_install_args_pins_exact_version(tmp_path: Path) -> None:
    node = tmp_path / "node"
    args = npm_install_args(node, "graphify", "2.1.0")
    combined = " ".join(args)
    assert "graphify@2.1.0" in combined


def test_npm_install_args_uses_prefix_flag(tmp_path: Path) -> None:
    node = tmp_path / "node"
    args = npm_install_args(node, "graphify", "2.1.0")
    assert "--prefix" in args
    assert str(node) in args


def test_npm_install_args_is_a_list_of_strings(tmp_path: Path) -> None:
    args = npm_install_args(tmp_path / "node", "graphify", "2.1.0")
    assert all(isinstance(a, str) for a in args)


def test_python_executable_is_inside_venv(tmp_path: Path) -> None:
    venv = tmp_path / "venv"
    exe = python_executable(venv)
    assert str(venv) in str(exe)


def test_bootstrap_pip_args_uses_venv_python(tmp_path: Path) -> None:
    venv = tmp_path / "venv"
    args = bootstrap_pip_args(venv)
    assert str(python_executable(venv)) == args[0]
    assert "ensurepip" in args

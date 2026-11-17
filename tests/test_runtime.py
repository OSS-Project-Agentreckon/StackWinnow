"""Tests for host environment inspection.

All tests are read-only: none install software, write files outside tmp_path,
or modify environment variables.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

from stackwinnow.contracts import OperationStatus, ProjectProfile
from stackwinnow.runtime import (
    _check_node,
    _check_python,
    _detect_assistant,
    _find_package_managers,
    inspect_environment,
)

# ---------------------------------------------------------------------------
# inspect_environment — top-level contract
# ---------------------------------------------------------------------------


def test_inspect_returns_profile_and_result_list(tmp_path: Path) -> None:
    profile, results = inspect_environment(str(tmp_path))
    assert isinstance(profile, ProjectProfile)
    assert isinstance(results, list)
    assert len(results) >= 3  # OS, Python, Node, package managers at minimum


def test_inspect_never_creates_files(tmp_path: Path) -> None:
    before = set(tmp_path.iterdir())
    inspect_environment(str(tmp_path))
    assert set(tmp_path.iterdir()) == before


def test_inspect_never_modifies_environment_variables(tmp_path: Path) -> None:
    before = dict(os.environ)
    inspect_environment(str(tmp_path))
    assert dict(os.environ) == before


def test_profile_always_contains_os_python_and_architecture(tmp_path: Path) -> None:
    profile, _ = inspect_environment(str(tmp_path))
    assert profile.operating_system is not None
    assert "python_version" in profile.facts
    assert "python_path" in profile.facts
    assert "architecture" in profile.facts
    assert "os" in profile.facts


def test_profile_project_root_is_preserved(tmp_path: Path) -> None:
    profile, _ = inspect_environment(str(tmp_path))
    assert profile.project_root == str(tmp_path)


# ---------------------------------------------------------------------------
# Python checks
# ---------------------------------------------------------------------------


def test_current_python_passes() -> None:
    version, result = _check_python()
    assert result.status == OperationStatus.SUCCEEDED
    expected = f"{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}"
    assert expected in result.message
    assert version == expected


def test_python_below_minimum_fails() -> None:
    with patch.object(sys, "version_info", (3, 9, 0)):
        version, result = _check_python()
    assert result.status == OperationStatus.FAILED
    assert "3.9" in result.message
    assert result.errors
    assert version == "3.9.0"


def test_python_failure_message_names_the_required_version() -> None:
    with patch.object(sys, "version_info", (3, 8, 10)):
        _, result = _check_python()
    assert "3.11" in result.message


# ---------------------------------------------------------------------------
# Node checks
# ---------------------------------------------------------------------------


def test_node_not_found_returns_blocked() -> None:
    with patch("stackwinnow.runtime.shutil.which", return_value=None):
        _, result = _check_node()
    assert result.status == OperationStatus.BLOCKED
    assert result.errors


def test_node_blocked_message_names_dependent_tools() -> None:
    with patch("stackwinnow.runtime.shutil.which", return_value=None):
        _, result = _check_node()
    assert "Graphify" in result.message or "Playwright" in result.message


def test_node_too_old_returns_failure() -> None:
    with (
        patch("stackwinnow.runtime.shutil.which", return_value="/usr/bin/node"),
        patch("stackwinnow.runtime._run_version", return_value="v16.20.0"),
    ):
        _, result = _check_node()
    assert result.status == OperationStatus.FAILED
    assert "16" in result.message
    assert result.errors


def test_node_current_version_returns_success() -> None:
    with (
        patch("stackwinnow.runtime.shutil.which", return_value="/usr/bin/node"),
        patch("stackwinnow.runtime._run_version", return_value="v20.11.0"),
    ):
        version, result = _check_node()
    assert result.status == OperationStatus.SUCCEEDED
    assert version == "20.11.0"
    assert "20.11.0" in result.message


def test_node_version_command_failure_returns_failed() -> None:
    with (
        patch("stackwinnow.runtime.shutil.which", return_value="/usr/bin/node"),
        patch("stackwinnow.runtime._run_version", return_value=None),
    ):
        version, result = _check_node()
    assert result.status == OperationStatus.FAILED
    assert version is None
    assert result.errors


def test_node_unparseable_version_returns_failed() -> None:
    with (
        patch("stackwinnow.runtime.shutil.which", return_value="/usr/bin/node"),
        patch("stackwinnow.runtime._run_version", return_value="not-a-version"),
    ):
        version, result = _check_node()
    assert result.status == OperationStatus.FAILED
    assert version is None


# ---------------------------------------------------------------------------
# Package managers
# ---------------------------------------------------------------------------


def test_find_package_managers_returns_present_ones() -> None:
    def fake_which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in ("pip", "npm") else None

    with patch("stackwinnow.runtime.shutil.which", side_effect=fake_which):
        found = _find_package_managers()
    assert "pip" in found
    assert "npm" in found
    assert "brew" not in found


def test_find_package_managers_returns_empty_when_none_present() -> None:
    with patch("stackwinnow.runtime.shutil.which", return_value=None):
        found = _find_package_managers()
    assert found == []


def test_no_package_managers_produces_failed_result(tmp_path: Path) -> None:
    with patch("stackwinnow.runtime.shutil.which", return_value=None):
        _, results = inspect_environment(str(tmp_path))
    pm_result = next(r for r in results if "package manager" in r.message.lower())
    assert pm_result.status == OperationStatus.FAILED
    assert pm_result.errors


# ---------------------------------------------------------------------------
# Assistant detection
# ---------------------------------------------------------------------------


def test_detect_claude_code_via_executable() -> None:
    def fake_which(name: str) -> str | None:
        return "/usr/local/bin/claude" if name == "claude" else None

    with patch("stackwinnow.runtime.shutil.which", side_effect=fake_which):
        assistant = _detect_assistant()
    assert assistant == "claude-code"


def test_detect_cursor_via_executable() -> None:
    def fake_which(name: str) -> str | None:
        return "/usr/local/bin/cursor" if name == "cursor" else None

    with patch("stackwinnow.runtime.shutil.which", side_effect=fake_which):
        assistant = _detect_assistant()
    assert assistant == "cursor"


def test_no_assistant_returns_none(tmp_path: Path) -> None:
    with (
        patch("stackwinnow.runtime.shutil.which", return_value=None),
        patch("pathlib.Path.is_dir", return_value=False),
    ):
        assistant = _detect_assistant()
    assert assistant is None


def test_detected_assistant_stored_in_profile(tmp_path: Path) -> None:
    def fake_which(name: str) -> str | None:
        return "/usr/local/bin/claude" if name == "claude" else None

    with patch("stackwinnow.runtime.shutil.which", side_effect=fake_which):
        profile, _ = inspect_environment(str(tmp_path))
    assert profile.assistant == "claude-code"
    assert profile.facts.get("assistant_detected") == ["claude-code"]


# ---------------------------------------------------------------------------
# Diagnostic quality — failures must be actionable
# ---------------------------------------------------------------------------


def test_all_failures_carry_actionable_errors() -> None:
    """Every FAILED or BLOCKED result must include at least one error string."""
    with patch("stackwinnow.runtime.shutil.which", return_value=None):
        _, node_result = _check_node()
    assert node_result.errors, "blocked node result must carry actionable errors"

    with patch.object(sys, "version_info", (3, 9, 0)):
        _, py_result = _check_python()
    assert py_result.errors, "failed python result must carry actionable errors"

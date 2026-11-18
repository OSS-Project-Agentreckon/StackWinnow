"""Tests for bounded subprocess execution.

None of these tests install software, modify system config, or write
files outside tmp_path. External commands used (echo, python -c, sleep)
are standard POSIX tools expected on CI.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

from stackwinnow.runner import (
    DEFAULT_TIMEOUT,
    CommandResult,
    _build_env,
    _redact_secrets,
    run_command,
)

# ---------------------------------------------------------------------------
# CommandResult
# ---------------------------------------------------------------------------


def test_zero_exit_with_no_timeout_is_succeeded() -> None:
    result = CommandResult(returncode=0, stdout="", stderr="")
    assert result.succeeded


def test_nonzero_exit_is_not_succeeded() -> None:
    result = CommandResult(returncode=1, stdout="", stderr="")
    assert not result.succeeded


def test_zero_exit_with_timeout_flag_is_not_succeeded() -> None:
    result = CommandResult(returncode=0, stdout="", stderr="", timed_out=True)
    assert not result.succeeded


# ---------------------------------------------------------------------------
# Successful execution
# ---------------------------------------------------------------------------


def test_successful_command_returns_succeeded(tmp_path: Path) -> None:
    result = run_command([sys.executable, "-c", "print('ok')"], cwd=tmp_path)
    assert result.succeeded
    assert result.returncode == 0


def test_stdout_is_captured(tmp_path: Path) -> None:
    result = run_command([sys.executable, "-c", "print('hello world')"], cwd=tmp_path)
    assert "hello world" in result.stdout


def test_stderr_is_captured(tmp_path: Path) -> None:
    result = run_command(
        [sys.executable, "-c", "import sys; sys.stderr.write('err msg\\n')"],
        cwd=tmp_path,
    )
    assert "err msg" in result.stderr


def test_space_in_cwd_does_not_cause_failure(tmp_path: Path) -> None:
    spaced = tmp_path / "my project folder"
    spaced.mkdir()
    result = run_command([sys.executable, "-c", "print('ok')"], cwd=spaced)
    assert result.succeeded


def test_space_in_arg_does_not_cause_injection(tmp_path: Path) -> None:
    result = run_command(
        [sys.executable, "-c", "import sys; print(sys.argv[1])", "hello world"],
        cwd=tmp_path,
    )
    assert result.succeeded
    assert "hello world" in result.stdout


# ---------------------------------------------------------------------------
# Failure cases
# ---------------------------------------------------------------------------


def test_nonzero_exit_returns_not_succeeded(tmp_path: Path) -> None:
    result = run_command([sys.executable, "-c", "raise SystemExit(1)"], cwd=tmp_path)
    assert not result.succeeded
    assert result.returncode == 1


def test_missing_command_returns_returncode_127(tmp_path: Path) -> None:
    result = run_command(["this-executable-does-not-exist-xyz"], cwd=tmp_path)
    assert not result.succeeded
    assert result.returncode == 127
    assert "not found" in result.stderr


def test_failed_command_cannot_be_mistaken_for_success(tmp_path: Path) -> None:
    result = run_command([sys.executable, "-c", "raise SystemExit(2)"], cwd=tmp_path)
    assert result.returncode == 2
    assert not result.succeeded


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


def test_timed_out_command_sets_timed_out_flag(tmp_path: Path) -> None:
    result = run_command(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        timeout=1,
    )
    assert result.timed_out
    assert not result.succeeded


def test_timed_out_command_returns_negative_returncode(tmp_path: Path) -> None:
    result = run_command(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        timeout=1,
    )
    assert result.returncode < 0


# ---------------------------------------------------------------------------
# Environment isolation
# ---------------------------------------------------------------------------


def test_sensitive_parent_env_var_not_forwarded_to_subprocess(tmp_path: Path) -> None:
    """Secrets present in the parent process must not reach managed tools."""
    sentinel = "SHOULD_NOT_APPEAR_IN_OUTPUT_XYZ987"
    with patch.dict(os.environ, {"MY_SECRET_KEY": sentinel}):
        result = run_command(
            [sys.executable, "-c", "import os; print(os.environ.get('MY_SECRET_KEY', 'absent'))"],
            cwd=tmp_path,
        )
    assert sentinel not in result.stdout
    assert "absent" in result.stdout


def test_extra_env_is_forwarded_to_subprocess(tmp_path: Path) -> None:
    result = run_command(
        [sys.executable, "-c", "import os; print(os.environ.get('MY_TOOL_VAR', 'missing'))"],
        cwd=tmp_path,
        extra_env={"MY_TOOL_VAR": "present"},
    )
    assert "present" in result.stdout


def test_sensitive_extra_env_value_is_redacted_in_output(tmp_path: Path) -> None:
    secret = "supersecret-value-123"
    result = run_command(
        [sys.executable, "-c", f"print('{secret}')"],
        cwd=tmp_path,
        extra_env={"MY_API_TOKEN": secret},
    )
    assert secret not in result.stdout
    assert "<redacted>" in result.stdout


# ---------------------------------------------------------------------------
# _build_env and _redact_secrets unit tests
# ---------------------------------------------------------------------------


def test_build_env_excludes_sensitive_parent_vars() -> None:
    with patch.dict(os.environ, {"AWS_SECRET_KEY": "leak-me", "PATH": "/usr/bin"}):
        env = _build_env(None)
    assert "AWS_SECRET_KEY" not in env


def test_build_env_includes_path() -> None:
    env = _build_env(None)
    assert "PATH" in env


def test_build_env_merges_extra_env() -> None:
    env = _build_env({"MY_EXTRA": "value"})
    assert env["MY_EXTRA"] == "value"


def test_redact_secrets_replaces_matching_values() -> None:
    env = {"MY_API_KEY": "s3cr3t"}
    result = _redact_secrets("the key is s3cr3t here", env)
    assert "s3cr3t" not in result
    assert "<redacted>" in result


def test_redact_secrets_leaves_non_sensitive_values_intact() -> None:
    env = {"MY_TOOL_NAME": "headroom"}
    result = _redact_secrets("tool is headroom", env)
    assert "headroom" in result


def test_default_timeout_is_positive() -> None:
    assert DEFAULT_TIMEOUT > 0

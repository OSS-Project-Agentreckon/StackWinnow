"""Bounded subprocess execution for declared adapter operations.

All commands are run as argument lists, never shell strings, to prevent
injection. Secrets from the parent process are not inherited by subprocesses.
A timed-out process is killed and the caller receives an explicit timed_out
result rather than a hung process.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Env-var name fragments that identify sensitive values.
_SENSITIVE_PATTERNS: tuple[str, ...] = (
    "_SECRET",
    "_KEY",
    "_TOKEN",
    "_PASSWORD",
    "_CREDENTIAL",
)

# Env-var names that are safe to pass through to subprocesses.
_PASSTHROUGH_VARS: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SystemRoot",
        "USERPROFILE",
    }
)

DEFAULT_TIMEOUT: int = 60


@dataclass(frozen=True)
class CommandResult:
    """Outcome of one bounded subprocess invocation."""

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def succeeded(self) -> bool:
        """True only when the process exited 0 and was not killed for timeout."""
        return self.returncode == 0 and not self.timed_out


def _build_env(extra: dict[str, str] | None) -> dict[str, str]:
    """Return a minimal subprocess environment.

    Inherits only a safe allowlist from the parent process so that
    credentials, virtualenv markers, and other parent-process state
    are not accidentally forwarded to managed tools.
    """
    env = {k: v for k, v in os.environ.items() if k in _PASSTHROUGH_VARS}
    if extra:
        env.update(extra)
    return env


def _redact_secrets(text: str, env: dict[str, str]) -> str:
    """Replace values of sensitive env vars with <redacted> in text."""
    for key, value in env.items():
        if value and any(pattern in key.upper() for pattern in _SENSITIVE_PATTERNS):
            text = text.replace(value, "<redacted>")
    return text


def run_command(
    args: list[str],
    *,
    cwd: str | Path,
    timeout: int = DEFAULT_TIMEOUT,
    extra_env: dict[str, str] | None = None,
) -> CommandResult:
    """Run args as a subprocess. Never uses shell=True.

    Sensitive values passed via extra_env are redacted from the returned
    stdout and stderr so diagnostics are safe to log.
    """
    env = _build_env(extra_env)
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return CommandResult(
            returncode=proc.returncode,
            stdout=_redact_secrets(proc.stdout, env),
            stderr=_redact_secrets(proc.stderr, env),
        )
    except subprocess.TimeoutExpired as exc:
        raw_out = exc.stdout or b""
        raw_err = exc.stderr or b""
        stdout = raw_out.decode(errors="replace") if isinstance(raw_out, bytes) else raw_out
        stderr = raw_err.decode(errors="replace") if isinstance(raw_err, bytes) else raw_err
        return CommandResult(
            returncode=-1,
            stdout=_redact_secrets(stdout, env),
            stderr=_redact_secrets(stderr, env),
            timed_out=True,
        )
    except FileNotFoundError:
        return CommandResult(
            returncode=127,
            stdout="",
            stderr=f"Command not found: {args[0]!r}",
        )

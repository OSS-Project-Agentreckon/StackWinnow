"""Bounded subprocess execution for declared adapter operations.

All commands are run as argument lists, never shell strings, to prevent
injection. Secrets from the parent process are not inherited by subprocesses.
A timed-out process group is killed and output cleanup is bounded. Descendants
that create a separate session are outside that group and may survive.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Sensitive words matched against each underscore-separated segment of an
# env-var name. Standalone names like TOKEN and PASSWORD are covered because
# splitting "TOKEN" on "_" yields {"TOKEN"}, which is in this set.
_SENSITIVE_WORDS: frozenset[str] = frozenset(
    {"SECRET", "KEY", "TOKEN", "PASSWORD", "CREDENTIAL", "API"}
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
_KILL_DRAIN_TIMEOUT: int = 2


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


def _is_sensitive_key(key: str) -> bool:
    """True if any underscore-separated word in the key name is a known secret word.

    Matches both prefixed names (MY_SECRET_KEY) and standalone names (TOKEN).
    """
    return bool(set(key.upper().split("_")) & _SENSITIVE_WORDS)


def _redact_secrets(text: str, env: dict[str, str]) -> str:
    """Replace sensitive env values in text.

    Values are replaced longest-first so that a short secret that is a prefix
    of a longer secret does not leave a partial match visible.
    """
    sensitive = sorted(
        (v for k, v in env.items() if v and _is_sensitive_key(k)),
        key=len,
        reverse=True,
    )
    for value in sensitive:
        text = text.replace(value, "<redacted>")
    return text


def _decode(data: bytes | str) -> str:
    """Decode bytes to str, replacing any undecodable sequences."""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data


def run_command(
    args: list[str],
    *,
    cwd: str | Path,
    timeout: int = DEFAULT_TIMEOUT,
    extra_env: dict[str, str] | None = None,
) -> CommandResult:
    """Run args as a subprocess. Never uses shell=True.

    Uses start_new_session=True so that on timeout the process group is killed.
    Children that detach into another session are not contained by this runner.
    Sensitive values passed via extra_env are redacted from the returned
    stdout and stderr so diagnostics are safe to log.
    """
    env = _build_env(extra_env)
    try:
        proc = subprocess.Popen(
            args,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,  # new session = new process group on POSIX
        )
        try:
            stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Kill the entire process group so no descendant outlives the timeout.
            if sys.platform != "win32":
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            proc.kill()
            try:
                stdout_bytes, stderr_bytes = proc.communicate(timeout=_KILL_DRAIN_TIMEOUT)
            except subprocess.TimeoutExpired as exc:
                # A descendant can escape the process group and retain a pipe.
                # Never wait for its EOF; return the captured output and close
                # our ends. This does not claim to terminate escaped sessions.
                stdout_bytes, stderr_bytes = exc.output or b"", exc.stderr or b""
                if proc.stdout is not None:
                    proc.stdout.close()
                if proc.stderr is not None:
                    proc.stderr.close()
                try:
                    proc.wait(timeout=_KILL_DRAIN_TIMEOUT)
                except subprocess.TimeoutExpired:
                    # Reaping may still be delayed after SIGKILL. Preserve the
                    # timed-out result rather than raising or waiting forever.
                    pass
            return CommandResult(
                returncode=-1,
                stdout=_redact_secrets(_decode(stdout_bytes), env),
                stderr=_redact_secrets(_decode(stderr_bytes), env),
                timed_out=True,
            )
        return CommandResult(
            returncode=proc.returncode,
            stdout=_redact_secrets(_decode(stdout_bytes), env),
            stderr=_redact_secrets(_decode(stderr_bytes), env),
        )
    except FileNotFoundError:
        return CommandResult(
            returncode=127,
            stdout="",
            stderr=f"Command not found: {args[0]!r}",
        )

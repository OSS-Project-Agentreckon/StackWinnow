"""Project-level exclusive operation lock for the managed .stackwinnow prefix.

Prevents concurrent StackWinnow operations on the same project from racing over
shared receipts or managed environments.  Uses O_CREAT | O_EXCL for atomic lock
creation; never follows symlinks on the lock path.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_STATE_DIR = ".stackwinnow"
_LOCK_FILE = "operation.lock"


class ProjectLockError(Exception):
    """Raised when the project operation lock cannot be acquired."""


@contextmanager
def project_lock(project_root: Path | str) -> Iterator[None]:
    """Exclusive per-project lock for managed installation operations.

    Acquires a lock scoped to *project_root* before yielding.  Releases it on
    exit, even if the body raises.  A second concurrent caller on the same root
    receives :exc:`ProjectLockError` immediately — it never waits.
    """
    managed = Path(project_root) / _STATE_DIR
    managed.mkdir(mode=0o700, exist_ok=True)
    lock_path = managed / _LOCK_FILE
    if lock_path.is_symlink():
        raise ProjectLockError(
            f"Lock path '{lock_path}' is a symlink; refusing to acquire. "
            "Remove the symlink before retrying."
        )
    try:
        fd = os.open(
            str(lock_path),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
            0o600,
        )
    except FileExistsError as exc:
        raise ProjectLockError(
            "Another StackWinnow operation is active for this project. "
            "If no other process is running, remove "
            f"'{lock_path}' and retry."
        ) from exc
    try:
        os.close(fd)
        yield
    finally:
        lock_path.unlink(missing_ok=True)

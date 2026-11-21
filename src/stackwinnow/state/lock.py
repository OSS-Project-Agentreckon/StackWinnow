"""Project-level exclusive operation lock for the managed .stackwinnow prefix.

Prevents concurrent StackWinnow operations on the same project from racing over
shared receipts or managed environments.  Uses O_CREAT | O_EXCL for atomic lock
creation; never follows symlinks on the lock path.
"""

from __future__ import annotations

import errno
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
    if managed.is_symlink():
        raise ProjectLockError(
            f"Managed directory '{managed}' is a symlink; refusing to acquire the lock. "
            "Remove the symlink before retrying."
        )
    # Track whether we created the directory so we can remove it on the way out if
    # nothing was written — otherwise a failed or dry run would leave an empty
    # .stackwinnow/ behind that wasn't there before.
    dir_created_here = not managed.exists()
    managed.mkdir(mode=0o700, exist_ok=True)
    # Second check closes the TOCTOU window between the first is_symlink() and mkdir():
    # a racing attacker could replace the path with a symlink in that gap.
    if managed.is_symlink():
        raise ProjectLockError(
            f"Managed directory '{managed}' is a symlink; refusing to acquire the lock. "
            "Remove the symlink before retrying."
        )
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
    except OSError as exc:
        # O_NOFOLLOW raises ELOOP on Linux when the path is a symlink; handle
        # it the same way as the explicit is_symlink() check above.
        if exc.errno == errno.ELOOP:
            raise ProjectLockError(
                f"Lock path '{lock_path}' is a symlink; refusing to acquire. "
                "Remove the symlink before retrying."
            ) from exc
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
        if dir_created_here:
            try:
                # rmdir() fails silently if the directory is non-empty, so this is
                # safe: it only removes the directory when nothing was persisted there.
                managed.rmdir()
            except OSError:
                pass

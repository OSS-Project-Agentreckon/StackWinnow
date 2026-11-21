"""Small bounded readers and path guards for managed Playwright state."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from stackwinnow.installer import ExecutionRecord


class ManagedStateError(ValueError):
    """An owned path requires manual inspection before further execution."""


def directories(root: Path, relative: str, *, create: bool = False) -> Path:
    current = root
    for part in Path(relative).parts:
        current /= part
        try:
            if create:
                current.mkdir(mode=0o700)
        except FileExistsError:
            pass
        try:
            if not stat.S_ISDIR(current.lstat().st_mode):
                raise ManagedStateError("Managed parents must be real directories, not symlinks.")
        except FileNotFoundError:
            if not create:
                break
            raise
    return root / relative


def read_file(path: Path, *, limit: int = 4 * 1024 * 1024) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
            raise ManagedStateError("Managed file is linked, special or too large.")
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        if len(raw) > limit or (
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ManagedStateError("Managed file changed while being read or is too large.")
        return raw


def read_json(path: Path) -> dict:
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ManagedStateError("Managed JSON has duplicate keys.")
            value[key] = item
        return value

    def invalid(value):
        raise ManagedStateError("Managed JSON contains a non-finite number.")

    try:
        value = json.loads(read_file(path), object_pairs_hook=pairs, parse_constant=invalid)
    except (ValueError, RecursionError) as exc:
        raise ManagedStateError("Managed JSON is invalid; inspect it before retrying.") from exc
    if not isinstance(value, dict):
        raise ManagedStateError("Managed JSON must be an object.")
    return value


def record_for(root: Path) -> ExecutionRecord:
    directories(root, ".stackwinnow")
    path = root / ".stackwinnow/receipts.json"
    if not path.exists() and not path.is_symlink():
        return ExecutionRecord(project_root=str(root))
    record = ExecutionRecord.model_validate(read_json(path))
    if record.project_root != str(root):
        raise ManagedStateError("Receipts belong to another project.")
    if len({step.step_id for step in record.steps}) != len(record.steps):
        raise ManagedStateError("Receipts contain duplicate step IDs.")
    record.steps = [step for step in record.steps if not step.dry_run]
    return record

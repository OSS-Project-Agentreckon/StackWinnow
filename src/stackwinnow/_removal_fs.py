"""Bounded descriptor-based snapshots and deletion of reviewed runtime trees."""

from __future__ import annotations

import hashlib
import json
import os
import stat

from stackwinnow.configure.patches import _parent, _stamp
from stackwinnow.installer import InstallerError

FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _names(directory, limit):
    names = []
    with os.scandir(directory) as entries:
        for entry in entries:
            names.append(entry.name)
            if len(names) > limit:
                raise InstallerError("Runtime directory exceeds its reviewed entry limit.")
    return sorted(names)


def _inventory(parent: int, name: str) -> dict[str, tuple]:
    entries: dict[str, tuple] = {}
    total = 0

    def visit(fd, leaf, path, depth):
        nonlocal total
        if depth > 80 or len(entries) >= 100000:
            raise InstallerError("Runtime snapshot exceeds 100000 entries or 80 levels.")
        info = os.stat(leaf, dir_fd=fd, follow_symlinks=False)
        stamp = _stamp(info)
        if stat.S_ISDIR(info.st_mode):
            child = os.open(leaf, FLAGS, dir_fd=fd)
            try:
                if _stamp(os.fstat(child)) != stamp:
                    raise InstallerError("Runtime changed while opening its directory.")
                entries[path] = ("directory", stamp)
                for item in _names(child, 100000 - len(entries)):
                    visit(child, item, path + "/" + item, depth + 1)
                if _stamp(os.fstat(child)) != stamp:
                    raise InstallerError("Runtime changed during its snapshot.")
            finally:
                os.close(child)
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            total += info.st_size
            if total > 2 * 1024**3:
                raise InstallerError("Runtime snapshot exceeds 2 GiB.")
            source = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            try:
                digest = hashlib.sha256()
                consumed = 0
                if _stamp(os.fstat(source)) != stamp:
                    raise InstallerError("Runtime changed while opening its file.")
                while chunk := os.read(source, 1024 * 1024):
                    consumed += len(chunk)
                    if consumed > info.st_size:
                        raise InstallerError("Runtime file grew beyond its reviewed size.")
                    digest.update(chunk)
                if _stamp(os.fstat(source)) != stamp:
                    raise InstallerError("Runtime changed while reading its file.")
                entries[path] = ("file", stamp, digest.hexdigest())
            finally:
                os.close(source)
        elif stat.S_ISLNK(info.st_mode):
            # npm bin links are removed as links, never followed to their targets.
            entries[path] = ("link", stamp, os.readlink(leaf, dir_fd=fd))
        else:
            raise InstallerError("Runtime contains a hard-linked or special file; preserve it.")
        if _stamp(os.stat(leaf, dir_fd=fd, follow_symlinks=False)) != stamp:
            raise InstallerError("Runtime changed during its snapshot.")

    visit(parent, name, ".", 0)
    return entries


def _digest(entries):
    return hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()


def snapshot(root: str, relative: str) -> str | None:
    try:
        with _parent(root, relative) as (parent, name):
            if stat.S_ISLNK(os.stat(name, dir_fd=parent, follow_symlinks=False).st_mode):
                raise InstallerError("Runtime root is a symlink; preserve it.")
            return _digest(_inventory(parent, name))
    except FileNotFoundError:
        return None


def remove_tree(root: str, relative: str, expected: str) -> None:
    """Remove only a reviewed tree, anchored to open directory descriptors."""
    with _parent(root, relative) as (parent, name):
        entries = _inventory(parent, name)
        if _digest(entries) != expected:
            raise InstallerError("Runtime changed since preview; preserve it and preview again.")
        parent_identity = os.fstat(parent)
        with _parent(root, relative) as (current, _):
            if (os.fstat(current).st_dev, os.fstat(current).st_ino) != (
                parent_identity.st_dev,
                parent_identity.st_ino,
            ):
                raise InstallerError("Runtime parent moved during removal.")

        child_names: dict[str, list[str]] = {}
        for path in entries:
            if path != ".":
                folder, leaf = path.rsplit("/", 1)
                child_names.setdefault(folder, []).append(leaf)

        def remove(fd, leaf, path):
            kind, stamp, *_ = entries[path]
            now = os.stat(leaf, dir_fd=fd, follow_symlinks=False)
            if _stamp(now) != stamp:
                raise InstallerError(
                    "Runtime entry changed during removal; inspect partial cleanup."
                )
            if kind == "directory":
                child = os.open(leaf, FLAGS, dir_fd=fd)
                try:
                    if _stamp(os.fstat(child)) != stamp:
                        raise InstallerError("Runtime directory changed during removal.")
                    wanted = sorted(child_names.get(path, []))
                    children = _names(child, len(wanted))
                    if children != wanted:
                        raise InstallerError("Runtime gained unreviewed entries during removal.")
                    for item in children:
                        remove(child, item, path + "/" + item)
                    current = os.stat(leaf, dir_fd=fd, follow_symlinks=False)
                    if (current.st_dev, current.st_ino) != (stamp[0], stamp[1]):
                        raise InstallerError("Runtime directory moved during removal.")
                    os.rmdir(leaf, dir_fd=fd)
                finally:
                    os.close(child)
            else:
                os.unlink(leaf, dir_fd=fd)

        remove(parent, name, ".")

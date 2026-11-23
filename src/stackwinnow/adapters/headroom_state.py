"""Owned Headroom runtime inventory and isolated mutable data paths."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from stackwinnow.adapters._managed import directories, record_for
from stackwinnow.adapters.graphify_index import _publish
from stackwinnow.adapters.graphify_plan import _digest, _json, _read_at
from stackwinnow.contracts import EvidenceRef
from stackwinnow.installer import _persist

VERSION = "0.44.0"
ENV = ".stackwinnow/envs/headroom/python"
STATE = ".stackwinnow/headroom"
CACHE = STATE + "/cache/tiktoken"
REPORTS = STATE + "/reports"
MANIFEST = ENV + "/stackwinnow-installation.json"


class HeadroomStateError(ValueError):
    """Current ownership or runtime evidence is unavailable."""


def environment(root: Path) -> dict[str, str]:
    home = root / STATE / "home"
    return {
        "HOME": str(home),
        "TMPDIR": str(root / STATE / "tmp"),
        "TMP": str(root / STATE / "tmp"),
        "TEMP": str(root / STATE / "tmp"),
        "PIP_INDEX_URL": "https://pypi.org/simple",
        "PIP_EXTRA_INDEX_URL": "",
        "PIP_NO_INPUT": "1",
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "TIKTOKEN_CACHE_DIR": str(root / CACHE),
        "PIP_CONFIG_FILE": "/dev/null",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        "DO_NOT_TRACK": "1",
    }


def prepare_private_paths(root: Path, *, create: bool = True) -> None:
    for relative in (STATE + "/home/.config", STATE + "/home/.cache", STATE + "/tmp", CACHE):
        directories(root, relative, create=create)
    # Tokenizer loaders can read or replace cache files. Never follow an alias.
    for directory, subdirs, filenames in os.walk(root / CACHE, followlinks=False):
        for name in subdirs + filenames:
            path = Path(directory) / name
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or (
                not stat.S_ISDIR(metadata.st_mode)
                and (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1)
            ):
                raise HeadroomStateError(
                    "Headroom tokenizer cache contains an unsafe alias or file."
                )


def inventory(root: Path) -> dict[str, str]:
    directories(root, ENV)
    if not (root / ENV).is_dir():
        raise HeadroomStateError("Owned Headroom runtime is missing.")
    result: dict[str, str] = {}
    total = 0

    def unreadable(error):
        raise HeadroomStateError("Cannot inspect the complete Headroom runtime.") from error

    for directory, subdirs, filenames in os.walk(root / ENV, followlinks=False, onerror=unreadable):
        for name in subdirs:
            if not stat.S_ISDIR((Path(directory) / name).lstat().st_mode):
                raise HeadroomStateError("Headroom runtime contains a linked directory.")
        for name in filenames:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if relative == MANIFEST:
                continue
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise HeadroomStateError("Headroom runtime contains a linked or special file.")
            total += metadata.st_size
            if total > 1024 * 1024 * 1024 or len(result) >= 40000:
                raise HeadroomStateError("Headroom runtime exceeds inventory limits.")
            raw = _read_at(root, relative, limit=128 * 1024 * 1024)
            result[relative] = f"{stat.S_IMODE(metadata.st_mode):o}:{_digest(raw)}"
    return result


def owned_paths(root: Path) -> list[str]:
    return [str(root / ENV), STATE]


def inspect_installation(root: Path) -> tuple[dict, str] | None:
    """Read-only current inventory validation; old metadata-only receipts cannot pass."""
    record = record_for(root)
    directories(root, ENV)
    directories(root, STATE)
    receipts = [
        receipt
        for receipt in record.steps
        if str(root / ENV) in receipt.owned_paths or ENV in receipt.owned_paths
    ]
    if not os.path.lexists(root / ENV):
        if receipts or os.path.lexists(root / STATE):
            raise HeadroomStateError("Headroom runtime is missing or partial; inspect owned state.")
        return None
    if not receipts:
        raise HeadroomStateError("The Headroom venv exists without an ownership receipt.")
    if any(
        r.tool_id != "headroom"
        or r.status != "succeeded"
        or r.owned_paths != owned_paths(root)
        or r.configuration_intents
        or r.configuration_ownership
        or not r.step_id.endswith("-install")
        for r in receipts
    ):
        raise HeadroomStateError("Partial or legacy Headroom ownership requires inspection.")
    try:
        raw = _read_at(root, MANIFEST, limit=16 * 1024 * 1024)
    except FileNotFoundError as exc:
        raise HeadroomStateError(
            "Legacy Headroom installation has no inventory; inspect it before recovery."
        ) from exc
    digest = _digest(raw)
    evidence = [EvidenceRef(source=MANIFEST, detail="sha256:" + digest)]
    if any(r.evidence != evidence for r in receipts):
        raise HeadroomStateError("Headroom installation evidence changed or is incomplete.")
    manifest = _json(raw)
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"schema_version", "project_root", "version", "health", "files"}
        or manifest["schema_version"] != 1
        or manifest["project_root"] != str(root)
        or manifest["version"] != VERSION
    ):
        raise HeadroomStateError("Headroom installation manifest is invalid.")
    validate_health(manifest["health"], root)
    if not manifest["files"] or manifest["files"] != inventory(root):
        raise HeadroomStateError("Headroom installation changed; inspect it before reuse.")
    if not (root / STATE).is_dir():
        raise HeadroomStateError("Owned Headroom data directory is missing.")
    prepare_private_paths(root, create=False)
    return manifest, digest


def health_script() -> str:
    return """# stackwinnow-headroom-health
import importlib.metadata as metadata, json, pathlib, sys
from headroom import compress
from tiktoken.model import encoding_name_for_model
assert callable(compress)
print(json.dumps({"prefix": str(pathlib.Path(sys.prefix).resolve()),
    "version": metadata.version("headroom-ai"),
    "tokenizer": encoding_name_for_model("gpt-4o"),
    "distributions": sorted([{"name": d.metadata["Name"], "version": d.version}
       for d in metadata.distributions()], key=lambda d: d["name"].lower())}))
"""


def validate_health(value: object, root: Path) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != {"prefix", "version", "tokenizer", "distributions"}
        or value["prefix"] != str(root / ENV)
        or value["version"] != VERSION
        or value["tokenizer"] != "o200k_base"
        or not isinstance(value["distributions"], list)
        or not value["distributions"]
    ):
        raise HeadroomStateError("Headroom health check did not identify the expected environment.")
    names = set()
    for item in value["distributions"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"name", "version"}
            or any(not isinstance(v, str) or not v.strip() for v in item.values())
        ):
            raise HeadroomStateError("Headroom dependency inventory is invalid.")
        name = item["name"].lower().replace("_", "-")
        if name in names:
            raise HeadroomStateError("Headroom dependency inventory contains duplicates.")
        names.add(name)
    if not any(
        d["name"] == "headroom-ai" and d["version"] == VERSION for d in value["distributions"]
    ):
        raise HeadroomStateError("Headroom dependency inventory omits the pinned package.")


def journal_paths(root: Path, step_id: str, paths: list[str]) -> None:
    """Record each created root immediately, while the shared executor lock is held."""
    record = record_for(root)
    receipt = record.receipt_for(step_id)
    if receipt is None or receipt.tool_id != "headroom" or receipt.status != "failed":
        raise HeadroomStateError("Headroom installation intent is unavailable.")
    receipt.owned_paths[:] = paths
    _persist(record, project_root=str(root))


def write_manifest(root: Path, health: dict) -> str:
    import json

    validate_health(health, root)
    files = inventory(root)
    if ENV + "/bin/python" not in files:
        raise HeadroomStateError("Headroom runtime did not produce its interpreter.")
    raw = json.dumps(
        {
            "schema_version": 1,
            "project_root": str(root),
            "version": VERSION,
            "health": health,
            "files": files,
        },
        sort_keys=True,
        indent=2,
    ).encode()
    _publish(root, MANIFEST, raw)
    return _digest(raw)

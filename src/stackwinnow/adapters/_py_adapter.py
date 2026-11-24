"""Shared venv + pip + health pattern for simple Python library adapters.

Each tool that uses this base gets an isolated venv under
.stackwinnow/envs/<tool_id>/python, a sanitised home/tmp tree under
.stackwinnow/<tool_id>/, and a manifest that records installed distributions.
No network calls beyond the initial pip install are made during verification.
"""

from __future__ import annotations

import json
from pathlib import Path

from stackwinnow.adapters._managed import ManagedStateError, directories, record_for
from stackwinnow.adapters.graphify_index import _publish
from stackwinnow.adapters.graphify_plan import _digest, _json, _read_at
from stackwinnow.contracts import (
    EvidenceRef,
    InstallPlan,
    OperationStatus,
    PlanStep,
)
from stackwinnow.environments import (
    EnvironmentBoundaryError,
    bootstrap_pip_args,
    create_venv_args,
    pip_install_args,
    python_env_path,
    python_executable,
)
from stackwinnow.installer import InstallerError, RunnerOutcome


def _env_relative(tool_id: str) -> str:
    return f".stackwinnow/envs/{tool_id}/python"


def _manifest_relative(tool_id: str) -> str:
    return f".stackwinnow/envs/{tool_id}/python/stackwinnow-installation.json"


def _state_relative(tool_id: str) -> str:
    return f".stackwinnow/{tool_id}"


def _env_path(root: Path, tool_id: str) -> Path:
    return python_env_path(str(root), tool_id)


def _reject_link(path: Path, label: str = "managed path") -> None:
    if path.is_symlink():
        raise ManagedStateError(
            f"The {label} '{path}' is a symbolic link; "
            "refusing to install outside the project boundary. "
            "Remove the symlink before retrying."
        )


def build_environment(root: Path, tool_id: str) -> dict[str, str]:
    state = root / _state_relative(tool_id)
    home = state / "home"
    return {
        "HOME": str(home),
        "TMPDIR": str(state / "tmp"),
        "TMP": str(state / "tmp"),
        "TEMP": str(state / "tmp"),
        "PIP_INDEX_URL": "https://pypi.org/simple",
        "PIP_EXTRA_INDEX_URL": "",
        "PIP_NO_INPUT": "1",
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "PIP_CONFIG_FILE": "/dev/null",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "DO_NOT_TRACK": "1",
    }


def prepare_private_paths(root: Path, tool_id: str, *, create: bool = True) -> None:
    state = _state_relative(tool_id)
    for relative in (state + "/home/.config", state + "/home/.cache", state + "/tmp"):
        directories(root, relative, create=create)


def build_install_plan(
    root: Path, tool_id: str, package_name: str, version: str, run_id: str
) -> InstallPlan:
    return InstallPlan(
        project_root=str(root),
        tool_ids=[tool_id],
        steps=[
            PlanStep(
                step_id=f"{tool_id}-{run_id}-install",
                tool_id=tool_id,
                description=f"Create Python venv and install {package_name}@{version}.",
            ),
            PlanStep(
                step_id=f"{tool_id}-{run_id}-verify",
                tool_id=tool_id,
                description=f"Import {package_name} and record installation evidence.",
            ),
        ],
    )


def health_script(tool_id: str, module_name: str, dist_name: str) -> str:
    return f"""# stackwinnow-{tool_id}-health
import importlib.metadata as metadata, json, pathlib, sys
import {module_name}  # noqa: F401
print(json.dumps({{
    "prefix": str(pathlib.Path(sys.prefix).resolve()),
    "version": metadata.version("{dist_name}"),
    "distributions": sorted(
        [{{"name": d.metadata["Name"], "version": d.version}} for d in metadata.distributions()],
        key=lambda d: d["name"].lower(),
    ),
}}))
"""


def inspect_installation(root: Path, tool_id: str, version: str) -> tuple[dict, str] | None:
    """Return (manifest, digest) if the tool is installed, else None; raise on corruption."""
    env = _env_path(root, tool_id)
    manifest = _manifest_relative(tool_id)
    record = record_for(root)
    env_tag = _env_relative(tool_id)
    receipts = [r for r in record.steps if env_tag in (r.owned_paths or [])]
    if not env.exists():
        if receipts:
            raise ManagedStateError(
                f"{tool_id} venv is missing but ownership records exist; inspect before retrying."
            )
        return None
    if not receipts:
        raise ManagedStateError(f"The {tool_id} venv exists without an ownership receipt.")
    if any(
        r.tool_id != tool_id or r.status != "succeeded" or not r.step_id.endswith("-install")
        for r in receipts
    ):
        raise ManagedStateError(f"Partial or inconsistent {tool_id} ownership; inspect receipts.")
    try:
        raw = _read_at(root, manifest, limit=4 * 1024 * 1024)
    except FileNotFoundError as exc:
        raise ManagedStateError(
            f"{tool_id} venv exists without installation manifest; inspect before retrying."
        ) from exc
    digest = _digest(raw)
    mf = _json(raw)
    if (
        not isinstance(mf, dict)
        or mf.get("schema_version") != 1
        or mf.get("project_root") != str(root)
        or mf.get("version") != version
        or mf.get("tool_id") != tool_id
    ):
        raise ManagedStateError(f"{tool_id} installation manifest is invalid or stale.")
    return mf, digest


def _write_manifest(root: Path, tool_id: str, version: str, health: dict) -> str:
    mf_path = _manifest_relative(tool_id)
    raw = json.dumps(
        {
            "schema_version": 1,
            "tool_id": tool_id,
            "project_root": str(root),
            "version": version,
            "health": health,
        },
        sort_keys=True,
        indent=2,
    ).encode()
    _publish(root, mf_path, raw)
    return _digest(raw)


def run_install_step(
    root: Path,
    step: PlanStep,
    runner,
    tool_id: str,
    package_name: str,
    version: str,
) -> RunnerOutcome:
    owned: list[str] = []
    env = _env_path(root, tool_id)
    state_rel = _state_relative(tool_id)
    env_rel = _env_relative(tool_id)
    label = "installation"
    try:
        existing = inspect_installation(root, tool_id, version)
        if existing is not None:
            return RunnerOutcome(
                status=OperationStatus.SUCCEEDED,
                message=f"{package_name} {version} reused (installation verified).",
                owned_paths=[env_rel, state_rel],
                evidence=[
                    EvidenceRef(source=_manifest_relative(tool_id), detail="sha256:" + existing[1])
                ],
            )
        _reject_link(env.parent, "tool directory")
        directories(root, _env_relative(tool_id).rsplit("/", 1)[0], create=True)
        env.mkdir(mode=0o700)
        owned.append(env_rel)
        if not record_for(root).retained_path(tool_id, state_rel):
            (root / state_rel).mkdir(mode=0o700)
        else:
            directories(root, state_rel, create=True)
        owned.append(state_rel)
        prepare_private_paths(root, tool_id)
        creation = create_venv_args(env)
        creation.insert(-1, "--copies")
        for args, timeout, label in (
            (_isolated(creation), 60, "venv creation"),
            (_isolated(bootstrap_pip_args(env)), 60, "pip bootstrap"),
            (
                _isolated(pip_install_args(env, package_name, version)),
                600,
                f"{package_name} install",
            ),
        ):
            outcome = runner(
                args, cwd=root, timeout=timeout, extra_env=build_environment(root, tool_id)
            )
            if not outcome.succeeded:
                return RunnerOutcome(
                    status=OperationStatus.FAILED,
                    message=label + (" timed out." if outcome.timed_out else " failed."),
                    owned_paths=owned,
                )
        return RunnerOutcome(
            status=OperationStatus.SUCCEEDED,
            message=f"{package_name} {version} installed.",
            owned_paths=owned,
        )
    except (OSError, ValueError, RuntimeError, InstallerError, EnvironmentBoundaryError):
        return RunnerOutcome(
            status=OperationStatus.FAILED,
            message=f"{tool_id} {label} failed; inspect retained ownership before retrying.",
            owned_paths=owned,
        )


def run_verify_step(
    root: Path,
    step: PlanStep,
    runner,
    tool_id: str,
    module_name: str,
    dist_name: str,
    version: str,
) -> RunnerOutcome:
    env = _env_path(root, tool_id)
    label = "verification"
    try:
        prepare_private_paths(root, tool_id)
        script = health_script(tool_id, module_name, dist_name)
        outcome = runner(
            [str(python_executable(env)), "-I", "-B", "-c", script],
            cwd=root,
            timeout=60,
            extra_env=build_environment(root, tool_id),
        )
        if not outcome.succeeded or len(outcome.stdout.encode()) > 256 * 1024:
            raise ManagedStateError(f"{tool_id} health check failed.")
        health = _json(outcome.stdout.encode())
        if not isinstance(health, dict) or health.get("version") != version:
            raise ManagedStateError(f"{tool_id} reported version does not match pinned {version}.")
        digest = _write_manifest(root, tool_id, version, health)
        return RunnerOutcome(
            status=OperationStatus.SUCCEEDED,
            message=f"{tool_id} {version} import and version verified.",
            owned_paths=[],
            evidence=[EvidenceRef(source=_manifest_relative(tool_id), detail="sha256:" + digest)],
        )
    except (OSError, ValueError, RuntimeError, InstallerError, ManagedStateError) as exc:
        return RunnerOutcome(
            status=OperationStatus.FAILED,
            message=f"{tool_id} {label} failed: {exc}",
        )


def _isolated(args: list[str]) -> list[str]:
    if len(args) >= 2 and args[1] == "-m":
        return [args[0], "-I", "-m"] + args[2:]
    return list(args)

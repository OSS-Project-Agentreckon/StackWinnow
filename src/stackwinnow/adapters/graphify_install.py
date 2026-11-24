"""Explicit install-only execution of the reviewed Graphify preparation.

This installs local packages. It neither indexes source nor edits client settings.
Receipts and an inventory bind repeat use to the exact successful installation;
partial or changed environments require inspection, never automatic adoption.
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from packaging.specifiers import SpecifierSet
from packaging.version import Version
from pydantic import Field

from stackwinnow.adapters._composition import validate_and_guard
from stackwinnow.adapters._managed import ManagedStateError, directories, record_for
from stackwinnow.adapters.graphify import STATE_PATH, GraphifyError, _root
from stackwinnow.adapters.graphify_plan import (
    ENV_PATH,
    GraphifyExecutionPlan,
    _digest,
    _json,
    _prepare_graphify_execution,
    _read_at,
    graphify_requirements,
    same_graphify_recipe,
)
from stackwinnow.contracts import (
    Contract,
    EvidenceRef,
    InstallPlan,
    OperationResult,
    OperationStatus,
    PlanStep,
)
from stackwinnow.installer import ExecutionRecord, InstallerError, RunnerOutcome, execute_plan
from stackwinnow.runner import CommandResult, run_command

INSTALL_ROOT = ".stackwinnow/envs/graphify"
MANIFEST = f"{INSTALL_ROOT}/installation.json"
STEP_ID = "graphify-install-locked"
CommandRunner = Callable[..., CommandResult]


def graphify_server_settings(root: Path) -> dict:
    """Register the manager bridge; the upstream package has no MCP subcommand."""
    import sys

    from stackwinnow.adapters.graphify import _environment
    from stackwinnow.graphify_bridge import TOOL

    python = root / ENV_PATH / "bin/python"
    return {
        "command": sys.executable,
        "args": [
            "-I",
            "-B",
            "-m",
            "stackwinnow.graphify_bridge",
            "--project",
            str(root),
            "--python",
            str(python),
        ],
        "cwd": str(root / STATE_PATH / "home"),
        "env": dict(_environment(root), PATH=str(Path(sys.executable).parent) + ":/usr/bin:/bin"),
        "enabled_tools": [TOOL],
        "startup_timeout_sec": 30,
        "tool_timeout_sec": 90,
    }


class GraphifyInstallResult(Contract):
    schema_version: Literal[1] = 1
    tool_id: Literal["graphify"] = "graphify"
    scope: Literal["local-install-only"] = "local-install-only"
    dry_run: bool
    installed: bool = False
    ready: Literal[False] = False
    record: ExecutionRecord
    results: list[OperationResult] = Field(default_factory=list)
    limitations: tuple[str, ...] = (
        "Indexing and shared Graphify verification require a separate indexing step.",
        "Client verification requires indexing and a configured Codex environment.",
    )


def _plan_digest(plan: GraphifyExecutionPlan) -> str:
    return _digest(plan.model_dump_json().encode())


def load_graphify_install_plan(path: str | Path) -> GraphifyExecutionPlan:
    """Read preparation, including an original plan reused after successful install."""
    try:
        selected = Path(path).absolute()
        plan = GraphifyExecutionPlan.model_validate(
            _json(_read_at(selected.parent, selected.name, limit=1024 * 1024))
        )
        _validate(plan)
        return plan
    except (OSError, ValueError, RuntimeError) as exc:
        raise GraphifyError(
            "Cannot apply Graphify plan; inspect the plan and project state."
        ) from exc


def _inventory(root: Path) -> dict[str, str]:
    """Hash regular install files and reject links/special files, including directories.

    --copies avoids interpreter symlinks. A bounded inventory is only a local
    change detector, not protection against someone rewriting both receipts
    and installation data.
    """
    directories(root, INSTALL_ROOT)
    if not (root / INSTALL_ROOT).is_dir():
        raise GraphifyError("The owned Graphify installation is missing.")
    found: dict[str, str] = {}
    total = 0

    def unreadable(error: OSError) -> None:
        raise GraphifyError("Cannot inspect all Graphify installation files.") from error

    for directory, subdirs, filenames in os.walk(
        root / INSTALL_ROOT, followlinks=False, onerror=unreadable
    ):
        for name in subdirs:
            if not stat.S_ISDIR((Path(directory) / name).lstat().st_mode):
                raise GraphifyError("Graphify installation contains a linked directory.")
        for name in filenames:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if relative == MANIFEST:
                continue
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise GraphifyError("Graphify installation contains a linked or special file.")
            total += metadata.st_size
            if total > 512 * 1024 * 1024 or len(found) >= 20000:
                raise GraphifyError("Graphify installation exceeds inventory limits.")
            digest = _digest(_read_at(root, relative, limit=128 * 1024 * 1024))
            found[relative] = f"{stat.S_IMODE(metadata.st_mode):o}:{digest}"
    return found


def _validate(plan: GraphifyExecutionPlan) -> bool:
    """Validate inputs and current ownership, returning whether reuse is allowed."""
    checked = GraphifyExecutionPlan.model_validate(plan.model_dump())
    root = _root(checked.project_root)
    record = record_for(root)
    existing = record.receipt_for(STEP_ID)
    current = _prepare_graphify_execution(
        root,
        expectation=checked.expectation,
        require_fresh=False,
        sources_override=checked.sources if existing is not None else None,
    )
    # Only the receipts snapshot may differ after this plan's successful apply.
    if not same_graphify_recipe(
        current.model_copy(update={"receipts_sha256": checked.receipts_sha256}), checked
    ):
        raise GraphifyError("Graphify plan or inputs changed; generate and review a new plan.")
    runtime = current.runtime
    if (
        runtime.implementation != "CPython"
        or runtime.system != "Darwin"
        or runtime.machine != "arm64"
        or not runtime.macos_version
        or Version(runtime.macos_version) < Version("14")
        or not SpecifierSet(">=3.11.5,<3.12").contains(runtime.version)
        or any(
            not SpecifierSet(w.requires_python).contains(runtime.version) for w in current.packages
        )
    ):
        raise GraphifyError("Installation requires CPython 3.11.5–3.11.x on macOS 14+ arm64.")
    record = record_for(root)
    own = [s for s in record.steps if s.tool_id == "graphify" and s.step_id == STEP_ID]
    if (
        not own
        and os.path.lexists(root / STATE_PATH)
        and not record.retained_path("graphify", STATE_PATH)
    ):
        raise GraphifyError(
            "Existing Graphify index state requires inspection before installation."
        )
    if not own:
        if record.receipt_for(STEP_ID) is not None:
            raise GraphifyError("Graphify's installation step ID is already owned by another tool.")
        if os.path.lexists(root / INSTALL_ROOT):
            raise GraphifyError("Refusing to adopt an existing, unowned Graphify environment.")
        if current.receipts_sha256 != checked.receipts_sha256:
            raise GraphifyError("Receipts changed; generate and review a new plan.")
        return False
    if (
        len(own) != 1
        or own[0].step_id != STEP_ID
        or own[0].status != OperationStatus.SUCCEEDED
        or own[0].owned_paths != [INSTALL_ROOT]
        or own[0].configuration_intents
    ):
        raise GraphifyError("Partial or unfamiliar Graphify state requires manual inspection.")
    # configuration_ownership may hold the graphify codex patch from a prior configure step.
    codex_ownership = own[0].configuration_ownership
    if codex_ownership and not all(
        p.tool_id == "graphify" and p.relative_path == ".codex/config.toml" for p in codex_ownership
    ):
        raise GraphifyError(
            "Graphify configuration ownership has unexpected patches; inspect before retrying."
        )
    raw = _read_at(root, MANIFEST)
    if own[0].evidence != [EvidenceRef(source=MANIFEST, detail=f"sha256:{_digest(raw)}")]:
        raise GraphifyError("Graphify installation evidence changed; inspect the owned state.")
    manifest = _json(raw)
    if (
        not _manifest_shape(manifest)
        or (manifest["schema_version"] == 2 and manifest["plan"] != checked.model_dump(mode="json"))
        or manifest["plan_sha256"] != _plan_digest(checked)
        or not manifest["files"]
        or manifest["files"] != _inventory(root)
    ):
        raise GraphifyError("Graphify installation changed; inspect it before reuse.")
    return True


def _manifest_shape(manifest: object) -> bool:
    return isinstance(manifest, dict) and (
        (
            manifest.get("schema_version") == 1
            and set(manifest) == {"schema_version", "plan_sha256", "files"}
        )
        or (
            manifest.get("schema_version") == 2
            and set(manifest) == {"schema_version", "plan_sha256", "plan", "files"}
        )
    )


def validate_graphify_installation(
    root: Path, installation_plan: GraphifyExecutionPlan | None = None
) -> tuple[GraphifyExecutionPlan, str]:
    """Inspect current inventory/recipe; legacy manifests need the original plan."""
    record = record_for(root)
    receipt = record.receipt_for(STEP_ID)
    if (
        receipt is None
        or not record.is_succeeded(STEP_ID, "graphify")
        or receipt.owned_paths != [INSTALL_ROOT]
        or receipt.configuration_intents
        or any(
            p.tool_id != "graphify"
            or p.project_root != str(root)
            or p.relative_path != ".codex/config.toml"
            for p in receipt.configuration_ownership
        )
    ):
        raise GraphifyError("A current owned Graphify installation is required.")
    raw = _read_at(root, MANIFEST)
    if receipt.evidence != [EvidenceRef(source=MANIFEST, detail=f"sha256:{_digest(raw)}")]:
        raise GraphifyError("Graphify installation evidence is missing or changed.")
    manifest = _json(raw)
    if not _manifest_shape(manifest):
        raise GraphifyError("Invalid installation manifest requires inspection before indexing.")
    if manifest["schema_version"] == 2:
        plan = GraphifyExecutionPlan.model_validate(manifest["plan"])
    else:
        if installation_plan is None:
            raise GraphifyError(
                "Legacy installation needs its original saved execution plan via --installation-plan."
            )
        plan = GraphifyExecutionPlan.model_validate(installation_plan.model_dump())
    if installation_plan is not None and installation_plan != plan:
        raise GraphifyError("Supplied installation plan differs from the owned recipe.")
    current = _prepare_graphify_execution(
        root, expectation=plan.expectation, require_fresh=False, sources_override=plan.sources
    )
    current = current.model_copy(update={"receipts_sha256": plan.receipts_sha256})
    if not same_graphify_recipe(current, plan) or manifest["plan_sha256"] != _plan_digest(plan):
        raise GraphifyError("Graphify installed recipe or runtime changed.")
    if not manifest["files"] or manifest["files"] != _inventory(root):
        raise GraphifyError("Graphify installation changed; inspect it before reuse.")
    return plan, _digest(raw)


_HEALTH_CHECK = """
import importlib.metadata as metadata
import json, pathlib, sys
assert pathlib.Path(sys.prefix).resolve() == pathlib.Path(sys.argv[1]).resolve()
for name, version in json.loads(sys.argv[2]).items():
    assert metadata.version(name) == version, name
import graphify, networkx, numpy, tree_sitter
print('Graphify locked environment verified.')
"""


def _install(plan: GraphifyExecutionPlan, runner: CommandRunner) -> RunnerOutcome:
    root = Path(plan.project_root)
    owned: list[str] = []
    phase = "create-environment"
    try:
        _root(root)
        directories(root, ".stackwinnow/envs", create=True)
        # Never adopt a directory that appears after validation.
        (root / INSTALL_ROOT).mkdir(mode=0o700)
        owned.append(INSTALL_ROOT)
        home = directories(root, f"{INSTALL_ROOT}/home", create=True)
        requirements = root / INSTALL_ROOT / "requirements.txt"
        with requirements.open("x", encoding="utf-8") as stream:
            stream.write(graphify_requirements())
        python = root / ENV_PATH / "bin/python"
        environment = {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "GRAPHIFY_NO_AUTO_REFRESH": "1",
            "GRAPHIFY_QUERY_LOG_DISABLE": "1",
        }
        commands = (
            (
                "create-environment",
                [
                    plan.runtime.executable,
                    "-I",
                    "-m",
                    "venv",
                    "--copies",
                    "--without-pip",
                    str(root / ENV_PATH),
                ],
                60,
            ),
            ("bootstrap-pip", [str(python), "-I", "-m", "ensurepip", "--default-pip"], 60),
            (
                "install-locked-wheels",
                [
                    str(python),
                    "-I",
                    "-m",
                    "pip",
                    "--isolated",
                    "install",
                    "--disable-pip-version-check",
                    "--no-cache-dir",
                    "--no-index",
                    "--no-deps",
                    "--require-hashes",
                    "--only-binary=:all:",
                    "-r",
                    str(requirements),
                ],
                600,
            ),
            (
                "verify-installed-packages",
                [
                    str(python),
                    "-I",
                    "-c",
                    _HEALTH_CHECK,
                    str(root / ENV_PATH),
                    json.dumps({w.name: w.version for w in plan.packages}, sort_keys=True),
                ],
                60,
            ),
        )
        for phase, argv, timeout in commands:
            _root(root)
            directories(root, INSTALL_ROOT)
            outcome = runner(argv, cwd=str(root), timeout=timeout, extra_env=environment)
            if not outcome.succeeded:
                return RunnerOutcome(
                    status=OperationStatus.FAILED,
                    message=f"Graphify {phase} failed"
                    + (" (timed out)." if outcome.timed_out else "."),
                    errors=["Inspect the partial owned installation before retrying."],
                    owned_paths=owned,
                )
        phase = "post-install-verification"
        # Verify source/runtime/recipe snapshots again without treating the new
        # intent receipt or the installation we just created as foreign state.
        current = _prepare_graphify_execution(
            root, expectation=plan.expectation, require_fresh=False
        )
        if not same_graphify_recipe(
            current.model_copy(update={"receipts_sha256": plan.receipts_sha256}), plan
        ):
            raise GraphifyError(
                "Inputs changed during installation; no successful receipt recorded."
            )
        files = _inventory(root)
        if not files or f"{ENV_PATH}/bin/python" not in files:
            raise GraphifyError("Installation did not produce its declared Python environment.")
        raw = json.dumps(
            {
                "schema_version": 2,
                "plan_sha256": _plan_digest(plan),
                "plan": plan.model_dump(mode="json"),
                "files": files,
            },
            sort_keys=True,
            indent=2,
        ).encode()
        if len(raw) > 4 * 1024 * 1024:
            raise GraphifyError("Graphify inventory exceeds its supported size.")
        with (root / MANIFEST).open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        return RunnerOutcome(
            status=OperationStatus.SUCCEEDED,
            message="Locked Graphify packages installed and checked; indexing/Codex setup pending.",
            owned_paths=owned,
            evidence=[EvidenceRef(source=MANIFEST, detail=f"sha256:{_digest(raw)}")],
        )
    except (OSError, ValueError, RuntimeError) as exc:
        return RunnerOutcome(
            status=OperationStatus.FAILED,
            message=f"Graphify {phase} could not complete ({type(exc).__name__}).",
            errors=["Inspect the partial installation and recorded ownership before retrying."],
            owned_paths=owned,
        )


def apply_graphify_install(
    plan: GraphifyExecutionPlan,
    *,
    dry_run: bool = False,
    command_runner: CommandRunner = run_command,
    before_execute: Callable[[], None] | None = None,
) -> GraphifyInstallResult:
    """Install only; invoking this API explicitly requests the limited scope."""
    try:
        plan = GraphifyExecutionPlan.model_validate(plan.model_dump())
        installed = _validate(plan)
        installation = InstallPlan(
            project_root=plan.project_root,
            assistant=plan.assistant,
            tool_ids=["graphify"],
            steps=[
                PlanStep(
                    step_id=STEP_ID,
                    tool_id="graphify",
                    description="Install and check the locked Graphify packages (no index or client configuration).",
                )
            ],
        )
        record, results = execute_plan(
            installation,
            dry_run=dry_run,
            before_execute=lambda: validate_and_guard(lambda: _validate(plan), before_execute),
            step_runner=lambda step: _install(plan, command_runner),
        )
        return GraphifyInstallResult(
            dry_run=dry_run,
            installed=installed if dry_run else record.is_succeeded(STEP_ID, "graphify"),
            record=record,
            results=results,
        )
    except GraphifyError:
        raise
    except (OSError, ValueError, RuntimeError, ManagedStateError, InstallerError) as exc:
        raise GraphifyError(f"Cannot install Graphify: {exc}") from exc

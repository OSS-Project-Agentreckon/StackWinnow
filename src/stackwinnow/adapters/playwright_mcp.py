"""Pinned, project-scoped Playwright MCP onboarding for Codex on macOS arm64."""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import tempfile
from collections.abc import Callable
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field

from stackwinnow.adapters._composition import validate_and_guard
from stackwinnow.adapters._managed import (
    ManagedStateError,
    directories,
    read_file,
    read_json,
    record_for,
)
from stackwinnow.catalog import load_catalog
from stackwinnow.configure.codex import (
    KEY,
    RELATIVE_PATH,
    SERVER,
    apply_codex_server,
    document,
    plan_codex_server,
)
from stackwinnow.configure.patches import ConfigurationError
from stackwinnow.contracts import (
    ConfigPatch,
    Contract,
    InstallPlan,
    OperationResult,
    OperationStatus,
    PlanStep,
)
from stackwinnow.installer import ExecutionRecord, InstallerError, RunnerOutcome, execute_plan
from stackwinnow.runner import run_command

VERSION = "0.0.86"
PLAYWRIGHT_VERSION = "1.66.0-alpha-2026-11-18"
CODEX_VERSION = "0.169.0"
STATE = ".stackwinnow/envs/playwright-mcp"
NODE = STATE + "/node"
BROWSER = (
    STATE
    + "/browsers/chromium_headless_shell-1255/chrome-headless-shell-mac-arm64/chrome-headless-shell"
)
PACKAGES = {
    "@playwright/mcp": (
        VERSION,
        "sha512-4SL9OSINmik3+EObCYJIxH8BkhcqqGU6CM8XIgztW015iBVR9WR6Q0xF180Ery+xuEVyyK5r6nC2bOg3zjgCoA==",
    ),
    "playwright": (
        PLAYWRIGHT_VERSION,
        "sha512-otQ+PFujQwUSpcLjoZ1zocwpEEF/5WhsBKaOuZeRhJ3ifjyRJJskKeosaw55WYdJzwlmfugK7OMX/tey1ExhWQ==",
    ),
    "playwright-core": (
        PLAYWRIGHT_VERSION,
        "sha512-VQ60tKPjqhf/3tHJGKuQ8Qn6e28Ziorhpmh4DGBZThgQp5geZeyKmuoJF2o/OwQBs5K7LNkhxNbOclBoAicqPg==",
    ),
}


class PlaywrightError(ManagedStateError):
    """The selected setup requires correction or explicit manual recovery."""


class PlaywrightPlan(Contract):
    schema_version: Literal[1] = 1
    tool_id: Literal["playwright-mcp"] = "playwright-mcp"
    assistant: Literal["codex"] = "codex"
    version: Literal["0.0.86"] = VERSION
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    project_root: str
    node: str
    launcher_sha256: str
    configuration: ConfigPatch
    installation: InstallPlan


class PlaywrightResult(Contract):
    plan: PlaywrightPlan
    status: OperationStatus
    message: str
    dry_run: bool = False
    results: list[OperationResult] = Field(default_factory=list)
    record: ExecutionRecord | None = None
    client_check: dict | None = None


def launcher() -> Path:
    return Path(str(files("stackwinnow").joinpath("data/playwright-launcher.cjs"))).resolve()


def environment(root: Path, node: str) -> dict[str, str]:
    state = root / STATE
    return {
        "PATH": str(Path(node).parent) + os.pathsep + os.defpath,
        "HOME": str(state / "home"),
        "TMPDIR": str(state / "tmp"),
        "TMP": str(state / "tmp"),
        "TEMP": str(state / "tmp"),
        "NPM_CONFIG_USERCONFIG": str(state / "user.npmrc"),
        "NPM_CONFIG_GLOBALCONFIG": str(state / "global.npmrc"),
        "NPM_CONFIG_CACHE": str(state / "npm-cache"),
        "PLAYWRIGHT_BROWSERS_PATH": str(state / "browsers"),
        "CI": "true",
    }


def settings(root: Path, node: str) -> dict:
    return {
        "command": node,
        "args": [
            str(launcher()),
            str(root / NODE / "node_modules/@playwright/mcp/cli.js"),
            "--headless",
            "--isolated",
            "--executable-path",
            str(root / BROWSER),
            "--ignore-roots",
            "--no-webmcp",
            "--block-service-workers",
            "--timeout-action",
            "5000",
            "--timeout-navigation",
            "10000",
            "--output-dir",
            str(root / STATE / "output"),
        ],
        "cwd": str(root / STATE / "work"),
        "env": environment(root, node),
        "startup_timeout_sec": 30,
        "tool_timeout_sec": 30,
        "enabled_tools": [
            "browser_navigate",
            "browser_click",
            "browser_evaluate",
            "browser_snapshot",
            "browser_close",
        ],
    }


def guard(root: Path) -> None:
    if os.name != "posix":
        raise PlaywrightError("Playwright setup currently requires macOS arm64.")
    for path in (
        ".codex",
        STATE,
        NODE + "/node_modules/@playwright/mcp",
        NODE + "/node_modules/playwright",
        NODE + "/node_modules/playwright-core",
        str(Path(BROWSER).parent),
        *(STATE + "/" + p for p in ("home", "tmp", "work", "output", "checks", "npm-cache")),
    ):
        directories(root, path)


def _owns(record: ExecutionRecord, path: Path) -> bool:
    return any(s.tool_id == "playwright-mcp" and str(path) in s.owned_paths for s in record.steps)


def packages_installed(root: Path) -> bool:
    guard(root)
    try:
        lock = read_json(root / NODE / "node_modules/.package-lock.json")["packages"]
        if set(lock) != {"node_modules/" + name for name in PACKAGES}:
            return False
        for name, (version, integrity) in PACKAGES.items():
            package = read_json(root / NODE / "node_modules" / name / "package.json")
            artifact = lock["node_modules/" + name]
            if (package.get("name"), package.get("version"), package.get("license")) != (
                name,
                version,
                "Apache-2.0",
            ):
                return False
            if (artifact.get("version"), artifact.get("integrity")) != (version, integrity):
                return False
            read_file(root / NODE / "node_modules" / name / "cli.js")
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def installed(root: Path) -> bool:
    if not packages_installed(root):
        return False
    try:
        import stat

        browser = root / BROWSER
        info = browser.lstat()
        return stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and os.access(browser, os.X_OK)
    except OSError:
        return False


def inspect_setup(root: Path, node: str) -> tuple[bool, bool]:
    guard(root)
    record = record_for(root)
    state = root / STATE
    exists = state.exists()
    retired = record.retained_path("playwright-mcp", STATE) and not _owns(record, state)
    if exists and not _owns(record, state) and not retired:
        raise PlaywrightError(
            "Playwright state exists without a real ownership receipt; inspect it."
        )
    ready = exists and installed(root)
    if retired and any(os.path.lexists(root / STATE / p) for p in ("node", "browsers")):
        raise PlaywrightError("Runtime paths appeared after removal; refusing to adopt them.")
    if exists and not ready and not retired:
        raise PlaywrightError(
            "Owned Playwright installation is incomplete or changed; inspect it before retrying."
        )
    path = root / RELATIVE_PATH
    configured = False
    if path.exists() or path.is_symlink():
        parsed = document(read_file(path))
        servers = parsed.get("mcp_servers", {})
        if not isinstance(servers, dict):
            raise PlaywrightError("mcp_servers must be a TOML table.")
        if SERVER in servers:
            desired = settings(root, node)
            if servers[SERVER] != desired:
                raise PlaywrightError(
                    "The Playwright server configuration changed; preserve it and review manually."
                )
            configured = any(
                patch.format == "toml"
                and patch.tool_id == "playwright-mcp"
                and patch.project_root == str(root)
                and patch.relative_path == RELATIVE_PATH
                and any(edit.key_path == KEY and edit.written == desired for edit in patch.edits)
                for receipt in record.steps
                if receipt.tool_id == "playwright-mcp"
                for patch in receipt.configuration_ownership
            )
            if not configured:
                raise PlaywrightError(
                    "The Playwright server table exists without ownership; it will not be adopted."
                )
    return bool(ready), configured


def revalidate_client_setup(root: Path, node: str, registration: dict) -> None:
    """The isolated client's result is usable only while the selected setup matches."""
    if settings(root, node) != registration or inspect_setup(root, node) != (True, True):
        raise PlaywrightError("Owned setup changed during client verification; inspect and retry.")


def _build(root: Path, run_id: str) -> PlaywrightPlan:
    if not root.is_dir() or root.resolve(strict=True) != root:
        raise PlaywrightError("Select an existing, unchanged project directory.")
    entry = load_catalog().get("playwright-mcp")
    if entry.license != "Apache-2.0" or entry.license_review != "reviewed":
        raise PlaywrightError("The Playwright source license review is unavailable.")
    node = shutil.which("node") or "node"
    if node != "node":
        node = str(Path(node).resolve())
    inspect_setup(root, node)
    steps = [
        (
            "install",
            f"Install @playwright/mcp@{VERSION} and Chromium headless shell revision 1255 under {STATE}.",
        ),
        ("configure", f"Register only {SERVER} in {RELATIVE_PATH} for Codex."),
        (
            "verify",
            "Exercise the selected registration through real Codex using a local scripted provider and browser fixture.",
        ),
    ]
    return PlaywrightPlan(
        run_id=run_id,
        project_root=str(root),
        node=node,
        launcher_sha256=hashlib.sha256(launcher().read_bytes()).hexdigest(),
        configuration=plan_codex_server(root, settings(root, node)),
        installation=InstallPlan(
            project_root=str(root),
            assistant="codex",
            tool_ids=["playwright-mcp"],
            steps=[
                PlanStep(
                    step_id=f"playwright-{run_id}-{action}",
                    tool_id="playwright-mcp",
                    description=description,
                )
                for action, description in steps
            ],
        ),
    )


def plan_playwright(project_root: str | Path, *, assistant: Literal["codex"]) -> PlaywrightPlan:
    if assistant != "codex":
        raise PlaywrightError("Select the supported Codex project integration.")
    return _build(Path(project_root).resolve(strict=True), uuid4().hex)


def load_playwright_plan(path: str | Path) -> PlaywrightPlan:
    return PlaywrightPlan.model_validate(read_json(Path(path)))


def _validate(plan: PlaywrightPlan) -> Path:
    root = Path(plan.project_root)
    if _build(root, plan.run_id) != plan:
        raise PlaywrightError("The plan, runtime or configuration changed; create a fresh plan.")
    record = record_for(root)
    if any(record.receipt_for(s.step_id) for s in plan.installation.steps):
        raise PlaywrightError("This plan was already attempted; create a fresh plan.")
    return root


@contextmanager
def operation_lock(root: Path):
    directories(root, ".stackwinnow", create=True)
    path = root / ".stackwinnow/playwright-mcp.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    except FileExistsError as exc:
        raise PlaywrightError(
            "Another Playwright operation may be active; inspect its lock before retrying."
        ) from exc
    os.close(fd)
    try:
        yield
    finally:
        path.unlink()


def prerequisites(root: Path, node: str, runner=run_command) -> tuple[str, str]:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise PlaywrightError(
            "This recipe is validated only on macOS arm64, Node 24 and Codex 0.169.0."
        )
    npm, codex = shutil.which("npm"), shutil.which("codex")
    if node == "node" or not npm or not codex:
        raise PlaywrightError("Install Node 24, npm and Codex CLI 0.169.0 before applying.")
    for executable, pattern, label in (
        (node, r"v24\.\d+\.\d+", "Node 24"),
        (codex, r"codex-cli 0\.169\.0", "Codex CLI 0.169.0"),
    ):
        with tempfile.TemporaryDirectory(prefix="sw-runtime-", dir="/tmp") as scratch:
            env = environment(root, node)
            env.update(HOME=scratch, CODEX_HOME=scratch, TMPDIR=scratch, TMP=scratch, TEMP=scratch)
            result = runner([executable, "--version"], cwd=scratch, timeout=15, extra_env=env)
        if not result.succeeded or not re.fullmatch(pattern, result.stdout.strip()):
            raise PlaywrightError(f"A working {label} is required.")
    return npm, codex


def apply_playwright(
    plan: PlaywrightPlan,
    *,
    dry_run: bool = False,
    command_runner=None,
    before_execute: Callable[[], None] | None = None,
) -> PlaywrightResult:
    checked = PlaywrightPlan.model_validate(plan.model_dump())
    runner = command_runner or run_command
    result = PlaywrightResult(
        plan=checked, status=OperationStatus.BLOCKED, message="Setup blocked.", dry_run=dry_run
    )
    try:
        root = _validate(checked)
        if dry_run:
            result.record, result.results = execute_plan(checked.installation, dry_run=True)
            result.status, result.message = (
                OperationStatus.SKIPPED,
                "Dry run; no commands or writes.",
            )
            return result
        npm, codex = prerequisites(root, checked.node, runner)
        env = environment(root, checked.node)

        def run_step(step):
            guard(root)
            if step.step_id.endswith("-install"):
                exists, _ = inspect_setup(root, checked.node)
                owned = [str(root / STATE)] if exists else []
                try:
                    if not exists:
                        directories(root, str(Path(STATE).parent), create=True)
                        # Exclusive creation prevents adopting a directory that appeared
                        # after inspection. Only a successful mkdir establishes ownership.
                        retired = record_for(root).retained_path("playwright-mcp", STATE)
                        if retired:
                            directories(root, STATE, create=True)
                        else:
                            (root / STATE).mkdir(mode=0o700)
                        owned.append(str(root / STATE))
                        for part in (
                            "node",
                            "home",
                            "tmp",
                            "work",
                            "output",
                            "checks",
                            "npm-cache",
                        ):
                            directories(root, STATE + "/" + part, create=True)
                        for name in ("user.npmrc", "global.npmrc"):
                            path = root / STATE / name
                            if retired and path.exists():
                                if read_file(path) != b"":
                                    raise PlaywrightError(
                                        "Retained npm settings changed; inspect them."
                                    )
                            else:
                                with path.open("xb"):
                                    pass
                        commands = [
                            [
                                npm,
                                "install",
                                "--prefix",
                                str(root / NODE),
                                "--save-exact",
                                "--registry=https://registry.npmjs.org",
                                "--ignore-scripts",
                                "--no-audit",
                                "--no-fund",
                                f"@playwright/mcp@{VERSION}",
                            ],
                            [
                                checked.node,
                                str(root / NODE / "node_modules/playwright/cli.js"),
                                "install",
                                "chromium",
                                "--only-shell",
                            ],
                        ]
                        for index, command in enumerate(commands):
                            if index == 1 and not packages_installed(root):
                                return RunnerOutcome(
                                    status=OperationStatus.FAILED,
                                    message="Pinned npm metadata did not match; browser installer was not executed.",
                                    owned_paths=owned,
                                )
                            outcome = runner(command, cwd=root / NODE, timeout=600, extra_env=env)
                            if not outcome.succeeded:
                                return RunnerOutcome(
                                    status=OperationStatus.FAILED,
                                    message="Installation failed or timed out; preserve the partial state for inspection.",
                                    owned_paths=owned,
                                )
                    if not installed(root):
                        return RunnerOutcome(
                            status=OperationStatus.FAILED,
                            message="Pinned package integrity metadata or Chromium prerequisite is missing.",
                            owned_paths=owned,
                        )
                    return RunnerOutcome(
                        status=OperationStatus.SUCCEEDED,
                        message="Verified pinned packages and managed Chromium headless shell.",
                        owned_paths=owned,
                    )
                except (OSError, ManagedStateError):
                    return RunnerOutcome(
                        status=OperationStatus.FAILED,
                        message="Installation could not complete; preserve partial state for inspection.",
                        owned_paths=owned,
                    )
            if step.step_id.endswith("-configure"):
                if not inspect_setup(root, checked.node)[0]:
                    raise PlaywrightError(
                        "The owned installation disappeared before configuration."
                    )
                parent = root / ".codex"
                created = not parent.exists()
                directories(root, ".codex", create=True)
                applied = apply_codex_server(checked.configuration)
                return RunnerOutcome(
                    status=applied.result.status,
                    message=applied.result.message,
                    configuration_ownership=[applied.ownership] if applied.ownership else [],
                    owned_paths=[str(parent)] if created else [],
                )
            if inspect_setup(root, checked.node) != (True, True):
                raise PlaywrightError("Owned setup is missing before client verification.")
            from stackwinnow.verify.playwright_client import run_client_check

            registration = settings(root, checked.node)
            result.client_check = run_client_check(root, registration, codex, runner=runner)
            try:
                revalidate_client_setup(root, checked.node, registration)
            except (OSError, ValueError):
                return RunnerOutcome(
                    status=OperationStatus.BLOCKED,
                    message="Owned setup changed during client verification; preserve changes and retry.",
                )
            return RunnerOutcome(
                status=OperationStatus.SUCCEEDED
                if result.client_check["functional"]
                else OperationStatus.FAILED,
                message=result.client_check["message"],
            )

        with operation_lock(root):
            _validate(checked)
            result.record, result.results = execute_plan(
                checked.installation,
                before_execute=lambda: validate_and_guard(
                    lambda: _validate(checked), before_execute
                ),
                step_runner=run_step,
                configuration_intents={
                    checked.installation.steps[1].step_id: [checked.configuration]
                },
            )
        result.status = next(
            (
                r.status
                for r in result.results
                if r.status in (OperationStatus.FAILED, OperationStatus.BLOCKED)
            ),
            OperationStatus.SUCCEEDED,
        )
        result.message = (
            "Playwright setup and Codex fixture check completed."
            if result.status == OperationStatus.SUCCEEDED
            else "Setup did not pass; inspect the step results before retrying."
        )
    except (OSError, ValueError, ConfigurationError, InstallerError) as exc:
        result.message = (
            str(exc)
            if isinstance(exc, (ManagedStateError, ConfigurationError))
            else f"Setup IO failed ({exc.strerror}); inspect the project receipts before retrying."
            if isinstance(exc, OSError)
            else "Setup state could not be validated; inspect the project and receipts."
        )
    return result

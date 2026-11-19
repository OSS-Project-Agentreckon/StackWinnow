"""Pinned promptfoo onboarding with owned configuration and recorded evaluations.

The shared command runner is an explicit dependency. Planning remains available
before that dependency is integrated; execution then returns an actionable block.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import shutil
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import Field, ValidationError, model_validator

from stackwinnow.catalog import CatalogError, load_catalog
from stackwinnow.configure import ConfigurationError, apply_json_edits, plan_json_edits
from stackwinnow.contracts import (
    ConfigPatch,
    Contract,
    EvidenceRef,
    InstallPlan,
    JsonConfigEdit,
    OperationResult,
    OperationStatus,
    PlanStep,
    UntrimmedText,
)
from stackwinnow.installer import (
    ExecutionRecord,
    InstallerError,
    RunnerOutcome,
    execute_plan,
    load_record,
)

VERSION = "0.125.1"
INTEGRITY = "sha512-nogBhixdp69icwkg1EI0syZ4zAmAjJyWeLcqxAkTldbHi0qirOslwHvkUQhQmg65lQLrIKyMOMLXlBlSc6LRrg=="
NODE_PREFIX = ".stackwinnow/envs/promptfoo/node"
STATE_PREFIX = ".stackwinnow/promptfoo"
MAX_JSON_BYTES = 4 * 1024 * 1024
Provider = Literal["deterministic", "openai"]
Scenario = Literal["pass", "fail"]


class PromptfooError(ValueError):
    """An invalid request or a project state requiring explicit recovery."""


class CommandOutcome(Protocol):
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool

    @property
    def succeeded(self) -> bool: ...


class CommandRunner(Protocol):
    def __call__(
        self,
        args: list[str],
        *,
        cwd: str | Path,
        timeout: int,
        extra_env: dict[str, str] | None = None,
    ) -> CommandOutcome: ...


class PromptfooPlan(Contract):
    schema_version: Literal[1] = 1
    tool_id: Literal["promptfoo"] = "promptfoo"
    version: Literal["0.125.1"] = VERSION
    integrity: str = INTEGRITY
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    project_root: UntrimmedText
    provider: Provider = "deterministic"
    model: str | None = None
    scenario: Scenario = "pass"
    provider_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    configuration: ConfigPatch
    installation: InstallPlan

    @model_validator(mode="after")
    def validate_provider(self) -> PromptfooPlan:
        if self.provider == "deterministic" and self.model is not None:
            raise ValueError("The deterministic provider has no model.")
        if self.provider == "openai":
            if self.model is None or not re.fullmatch(
                r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}", self.model
            ):
                raise ValueError("An explicit OpenAI model ID is required.")
            if self.scenario != "pass":
                raise ValueError("The negative control uses only the deterministic provider.")
        return self


class EvaluationSummary(Contract):
    provider: Provider
    scenario: Scenario
    successes: int = Field(ge=0)
    failures: int = Field(ge=0)
    errors: int = Field(ge=0)
    result_path: UntrimmedText
    process_returncode: int


class PromptfooResult(Contract):
    schema_version: Literal[1] = 1
    plan: PromptfooPlan
    status: OperationStatus
    message: str
    dry_run: bool = False
    results: list[OperationResult] = Field(default_factory=list)
    record: ExecutionRecord | None = None
    evaluation: EvaluationSummary | None = None


def _provider_path() -> Path:
    return Path(str(files("stackwinnow").joinpath("data/promptfoo-provider.cjs"))).resolve()


def _root(value: str | Path) -> Path:
    try:
        path = Path(value).resolve(strict=True)
        if not path.is_dir():
            raise PromptfooError("Select an existing project directory.")
        return path
    except (OSError, RuntimeError, ValueError) as exc:
        raise PromptfooError("Select an existing project directory.") from exc


def _regular_file(path: Path, *, limit: int = MAX_JSON_BYTES) -> None:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
        raise PromptfooError("A managed file is linked, special, or too large; inspect it first.")


def _read_regular_file(path: Path) -> tuple[bytes, os.stat_result]:
    if os.name != "posix":
        raise PromptfooError("Promptfoo onboarding currently requires POSIX file operations.")
    _regular_file(path)
    # A regular file can be replaced by a FIFO after lstat. NONBLOCK lets fstat
    # reject that opened object without waiting indefinitely for a FIFO writer.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise PromptfooError("Managed files must be regular files with one link.")
        raw = stream.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise PromptfooError("Managed file exceeds the supported size.")
    return raw, opened


def _read_json(path: Path) -> dict:
    raw, _ = _read_regular_file(path)

    def unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise PromptfooError("Managed JSON contains duplicate keys.")
            result[key] = item
        return result

    def reject_constant(value: str) -> None:
        raise PromptfooError("Managed JSON contains a non-finite number.")

    def finite_float(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise PromptfooError("Managed JSON contains a non-finite number.")
        return parsed

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_keys,
            parse_constant=reject_constant,
            parse_float=finite_float,
        )
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise PromptfooError("Managed JSON is malformed or too deeply nested.") from exc
    if not isinstance(value, dict):
        raise PromptfooError("Managed JSON must contain an object.")
    return value


def _guard_directories(root: Path) -> None:
    if os.name != "posix":
        raise PromptfooError("Promptfoo onboarding currently requires POSIX file operations.")
    for relative in (
        NODE_PREFIX + "/node_modules/promptfoo/dist/src",
        STATE_PREFIX + "/work",
        STATE_PREFIX + "/home",
        STATE_PREFIX + "/results",
        STATE_PREFIX + "/npm-cache",
        STATE_PREFIX + "/cache",
        STATE_PREFIX + "/logs",
        STATE_PREFIX + "/tmp",
    ):
        current = root
        for component in Path(relative).parts:
            current /= component
            try:
                mode = current.lstat().st_mode
            except FileNotFoundError:
                break
            if not stat.S_ISDIR(mode):
                raise PromptfooError("Managed paths must be real directories, not links or files.")
    receipts = root / ".stackwinnow/receipts.json"
    if receipts.exists() or receipts.is_symlink():
        _regular_file(receipts)
    work = root / STATE_PREFIX / "work"
    if work.exists() and any(work.iterdir()):
        raise PromptfooError("The private promptfoo working directory must remain empty.")


def _record(root: Path) -> ExecutionRecord:
    _guard_directories(root)
    try:
        return load_record(str(root))
    except InstallerError as exc:
        raise PromptfooError(
            "Existing receipts need recovery; inspect .stackwinnow/receipts.json."
        ) from exc


def _filename(provider: Provider) -> str:
    suffix = ".openai" if provider == "openai" else ""
    return f"promptfooconfig.stackwinnow{suffix}.json"


def _configuration(provider: Provider, model: str | None) -> dict:
    if provider == "deterministic":
        providers: list[object] = ["file://" + str(_provider_path())]
        prompt = "{{input}}"
    else:
        providers = [
            {
                "id": f"openai:chat:{model}",
                "config": {"apiKeyEnvar": "OPENAI_API_KEY", "max_tokens": 16, "temperature": 0},
            }
        ]
        prompt = "Convert this text to uppercase. Return only the converted text: {{input}}"
    return {
        "description": "StackWinnow onboarding check; deterministic results do not measure LLM quality.",
        "prompts": [prompt],
        "providers": providers,
        "defaultTest": {"vars": {"stackwinnowFail": "false"}},
        "tests": [
            {"vars": {"input": "hello"}, "assert": [{"type": "equals", "value": "HELLO"}]},
            {"vars": {"input": "world"}, "assert": [{"type": "equals", "value": "WORLD"}]},
        ],
    }


def _check_existing_configuration(root: Path, record: ExecutionRecord, relative: str) -> None:
    path = root / relative
    if not path.exists() and not path.is_symlink():
        return
    raw, opened = _read_regular_file(path)
    digest = hashlib.sha256(raw).hexdigest()
    mode = stat.S_IMODE(opened.st_mode)
    for receipt in reversed(record.steps):
        for ownership in reversed(receipt.configuration_ownership):
            if ownership.tool_id == "promptfoo" and ownership.relative_path == relative:
                if (
                    ownership.project_root == str(root)
                    and ownership.written_file.sha256 == digest
                    and ownership.written_file.mode == mode
                ):
                    return
                raise PromptfooError(
                    "Owned promptfoo configuration changed; preserve it and review manually."
                )
    raise PromptfooError(
        "The chosen configuration file already exists without StackWinnow ownership."
    )


def _installation(root: Path, run_id: str, provider: Provider, scenario: Scenario) -> InstallPlan:
    actions = [
        ("install", f"Install and verify promptfoo@{VERSION} in {NODE_PREFIX}."),
        ("configure", f"Apply owned keys in {_filename(provider)}."),
        ("evaluate", f"Run the {provider} {scenario} evaluation and record its result."),
    ]
    return InstallPlan(
        project_root=str(root),
        tool_ids=["promptfoo"],
        steps=[
            PlanStep(
                step_id=f"promptfoo-{run_id}-{action}", tool_id="promptfoo", description=description
            )
            for action, description in actions
        ],
    )


def _has_path_ownership(record: ExecutionRecord, path: Path) -> bool:
    return any(
        receipt.tool_id == "promptfoo" and str(path) in receipt.owned_paths
        for receipt in record.steps
    )


def _check_installation(root: Path, record: ExecutionRecord) -> bool:
    state = root / STATE_PREFIX
    if state.exists() and not _has_path_ownership(record, state):
        raise PromptfooError("The promptfoo state directory exists without an ownership receipt.")
    prefix = root / NODE_PREFIX
    if not prefix.exists():
        return False
    if not _has_path_ownership(record, prefix):
        raise PromptfooError(
            "The managed promptfoo prefix already exists without an ownership receipt."
        )
    if not _installed_release(prefix):
        raise PromptfooError(
            "The owned promptfoo installation is incomplete or changed; inspect it before retrying."
        )
    return True


def _build_plan(
    project_root: str | Path,
    *,
    provider: Provider,
    model: str | None,
    scenario: Scenario,
    run_id: str,
) -> PromptfooPlan:
    root = _root(project_root)
    try:
        entry = load_catalog().get("promptfoo")
    except KeyError as exc:
        raise PromptfooError("promptfoo is not in the tool catalog.") from exc
    except CatalogError as exc:
        raise PromptfooError("The tool catalog is unavailable or invalid.") from exc
    if entry.license != "MIT" or entry.license_review != "reviewed":
        raise PromptfooError("The promptfoo OSS license review is not available.")
    record = _record(root)
    _check_installation(root, record)
    relative = _filename(provider)
    _check_existing_configuration(root, record, relative)
    configuration = plan_json_edits(
        root,
        relative,
        tool_id="promptfoo",
        edits=[
            JsonConfigEdit(key_path=(key,), value=value)
            for key, value in _configuration(provider, model).items()
        ],
    )
    return PromptfooPlan(
        run_id=run_id,
        project_root=str(root),
        provider=provider,
        model=model,
        scenario=scenario,
        provider_sha256=hashlib.sha256(_provider_path().read_bytes()).hexdigest(),
        configuration=configuration,
        installation=_installation(root, run_id, provider, scenario),
    )


def plan_promptfoo(
    project_root: str | Path,
    *,
    provider: Provider = "deterministic",
    model: str | None = None,
    scenario: Scenario = "pass",
) -> PromptfooPlan:
    """Preview one explicit evaluation profile without commands, network, or writes."""
    return _build_plan(
        project_root, provider=provider, model=model, scenario=scenario, run_id=uuid4().hex
    )


def load_promptfoo_plan(path: str | Path) -> PromptfooPlan:
    """Load a bounded regular JSON plan without following a file symlink."""
    return PromptfooPlan.model_validate(_read_json(Path(path)))


def _validate_plan(root: Path, plan: PromptfooPlan) -> None:
    if str(_root(root)) != plan.project_root:
        raise PromptfooError("The project path now resolves elsewhere; create a new plan.")
    record = _record(root)
    if any(record.receipt_for(step.step_id) is not None for step in plan.installation.steps):
        raise PromptfooError(
            "This plan was already attempted. Create a new plan for a fresh evaluation."
        )
    expected = _build_plan(
        root,
        provider=plan.provider,
        model=plan.model,
        scenario=plan.scenario,
        run_id=plan.run_id,
    )
    if expected != plan:
        raise PromptfooError(
            "The plan or its input configuration changed; create and review a new plan."
        )


def _default_runner() -> CommandRunner | None:
    try:
        from stackwinnow.runner import run_command
    except ModuleNotFoundError as exc:
        if exc.name != "stackwinnow.runner":
            raise
        return None
    return run_command


def _mkdir(root: Path, relative: str) -> Path:
    current = root
    for component in Path(relative).parts:
        current /= component
        try:
            current.mkdir(mode=0o700)
        except FileExistsError:
            if not stat.S_ISDIR(current.lstat().st_mode):
                raise PromptfooError(
                    "A managed directory was replaced; inspect the project before retrying."
                ) from None
    return current


@contextmanager
def _operation_lock(root: Path) -> Iterator[None]:
    _mkdir(root, ".stackwinnow")
    lock_path = root / ".stackwinnow/promptfoo.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    except FileExistsError as exc:
        raise PromptfooError(
            "Another promptfoo operation may be active. Inspect the lock before retrying."
        ) from exc
    try:
        os.close(descriptor)
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def _empty_file(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        _regular_file(path, limit=0)
    else:
        os.close(descriptor)


def _environment(root: Path, node: str, *, api_key: str | None = None) -> dict[str, str]:
    state = root / STATE_PREFIX
    values = {
        "PATH": str(Path(node).parent) + os.pathsep + os.environ.get("PATH", ""),
        "HOME": str(state / "home"),
        "TMPDIR": str(state / "tmp"),
        "TMP": str(state / "tmp"),
        "TEMP": str(state / "tmp"),
        "NPM_CONFIG_USERCONFIG": str(state / "empty.npmrc"),
        "NPM_CONFIG_GLOBALCONFIG": str(state / "empty.global.npmrc"),
        "NPM_CONFIG_CACHE": str(state / "npm-cache"),
        "DOTENV_CONFIG_PATH": str(state / "empty.env"),
        "DOTENV_PATH": str(state / "empty.env"),
        "PROMPTFOO_DISABLE_TELEMETRY": "1",
        "PROMPTFOO_DISABLE_UPDATE": "1",
        "PROMPTFOO_DISABLE_SHARING": "1",
        "PROMPTFOO_CONFIG_DIR": str(state / "home"),
        "PROMPTFOO_CACHE_PATH": str(state / "cache"),
        "PROMPTFOO_LOG_DIR": str(state / "logs"),
        "LOG_LEVEL": "warn",
        "CI": "true",
    }
    if api_key is not None:
        values["OPENAI_API_KEY"] = api_key
    return values


def _prepare_private_files(root: Path) -> None:
    for directory in ("work", "home", "results", "npm-cache", "cache", "logs", "tmp"):
        _mkdir(root, f"{STATE_PREFIX}/{directory}")
    for filename in ("empty.npmrc", "empty.global.npmrc", "empty.env"):
        _empty_file(root / STATE_PREFIX / filename)
    _guard_directories(root)


def _installed_release(prefix: Path) -> bool:
    try:
        _regular_file(prefix / "node_modules/promptfoo/dist/src/entrypoint.js")
        package = _read_json(prefix / "node_modules/promptfoo/package.json")
        lock = _read_json(prefix / "node_modules/.package-lock.json")
        artifact = lock["packages"]["node_modules/promptfoo"]
        return (
            package["name"] == "promptfoo"
            and package["version"] == VERSION
            and package["license"] == "MIT"
            and artifact["version"] == VERSION
            and artifact["integrity"] == INTEGRITY
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _summary(path: Path, plan: PromptfooPlan, returncode: int) -> EvaluationSummary:
    report = _read_json(path)
    results = report["results"]
    if not isinstance(results, dict) or results.get("version") != 3:
        raise PromptfooError("The evaluation report has invalid results.")
    counts = results["stats"]
    if not isinstance(counts, dict):
        raise PromptfooError("The evaluation report has invalid totals.")
    keys = ("successes", "failures", "errors")
    if any(type(counts.get(key)) is not int or counts[key] < 0 for key in keys):
        raise PromptfooError("The evaluation report has invalid totals.")
    rows = results["results"]
    if (
        sum(counts[key] for key in keys) != 2
        or not isinstance(rows, list)
        or len(rows) != 2
        or any(not isinstance(row, dict) for row in rows)
    ):
        raise PromptfooError("The evaluation report does not contain the two expected cases.")
    if sum(row.get("success") is True for row in rows) != counts["successes"]:
        raise PromptfooError("The evaluation report totals disagree with its test results.")
    if any(type(row.get("testIdx")) is not int for row in rows) or {
        row["testIdx"] for row in rows
    } != {0, 1}:
        raise PromptfooError("The evaluation report does not identify the expected test cases.")
    expected_outputs = {0: "HELLO", 1: "WORLD"}
    for row in rows:
        if row.get("success") is True and (
            not isinstance(row.get("response"), dict)
            or row["response"].get("output") != expected_outputs[row["testIdx"]]
        ):
            raise PromptfooError("A successful evaluation case has an unexpected output.")
    return EvaluationSummary(
        provider=plan.provider,
        scenario=plan.scenario,
        result_path=str(path),
        process_returncode=returncode,
        **{key: counts[key] for key in keys},
    )


def apply_promptfoo(
    plan: PromptfooPlan,
    *,
    dry_run: bool = False,
    allow_provider_usage: bool = False,
    command_runner: CommandRunner | None = None,
) -> PromptfooResult:
    """Apply a reviewed plan. Paid provider execution needs an explicit separate opt-in."""
    checked = PromptfooPlan.model_validate_json(plan.model_dump_json())

    def blocked(message: str) -> PromptfooResult:
        return PromptfooResult(
            plan=checked, status=OperationStatus.BLOCKED, message=message, dry_run=dry_run
        )

    try:
        root = _root(checked.project_root)
        _validate_plan(root, checked)
        if dry_run:
            record, results = execute_plan(checked.installation, dry_run=True)
            return PromptfooResult(
                plan=checked,
                status=OperationStatus.SKIPPED,
                message="Dry run; no commands or files were created.",
                dry_run=True,
                record=record,
                results=results,
            )
        runner = command_runner or _default_runner()
        if runner is None:
            return blocked(
                "Promptfoo execution requires the shared command runner, which is unavailable in this build. Use a dry run or a build that includes the runner."
            )
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            return blocked(
                "The initial promptfoo adapter is validated on macOS arm64 with Node 24; other environments remain unverified."
            )
        api_key = None
        if checked.provider == "openai":
            if not allow_provider_usage:
                return blocked(
                    "OpenAI execution requires --allow-provider-usage; these requests may incur provider charges."
                )
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                return blocked("Set OPENAI_API_KEY explicitly for the requested provider run.")
        node = shutil.which("node")
        npm = shutil.which("npm")
        if node is None or npm is None:
            return blocked("Install Node 24 and npm before applying the promptfoo plan.")
        node = str(Path(node).resolve())
        environment = _environment(root, node)
        version = runner([node, "--version"], cwd=root, timeout=15, extra_env=environment)
        if not version.succeeded or not re.fullmatch(r"v24\.\d+\.\d+", version.stdout.strip()):
            return blocked("The initial promptfoo adapter requires a working Node 24 runtime.")
        evaluation: EvaluationSummary | None = None

        def run_step(step: PlanStep) -> RunnerOutcome:
            nonlocal evaluation
            _guard_directories(root)
            prefix = root / NODE_PREFIX
            work = root / STATE_PREFIX / "work"
            entrypoint = prefix / "node_modules/promptfoo/dist/src/entrypoint.js"
            if step.step_id.endswith("-install"):
                already_installed = _check_installation(root, load_record(str(root)))
                _prepare_private_files(root)
                owned_paths = [str(prefix), str(root / STATE_PREFIX)]
                if not already_installed:
                    if prefix.exists():
                        return RunnerOutcome(
                            status=OperationStatus.BLOCKED,
                            message="The installation prefix appeared or changed; inspect it before retrying.",
                        )
                    _mkdir(root, NODE_PREFIX)
                    command = [
                        npm,
                        "install",
                        "--prefix",
                        str(prefix),
                        "--save-exact",
                        "--registry=https://registry.npmjs.org",
                        "--ignore-scripts",
                        "--no-audit",
                        "--no-fund",
                        f"promptfoo@{VERSION}",
                    ]
                    outcome = runner(command, cwd=prefix, timeout=600, extra_env=environment)
                    if not outcome.succeeded:
                        return RunnerOutcome(
                            status=OperationStatus.FAILED,
                            message="Pinned promptfoo installation failed; inspect the managed prefix before retrying.",
                            errors=[
                                "The installation command timed out."
                                if outcome.timed_out
                                else f"npm exited with status {outcome.returncode}."
                            ],
                            owned_paths=owned_paths,
                        )
                if not _installed_release(prefix):
                    return RunnerOutcome(
                        status=OperationStatus.FAILED,
                        message="The installed package does not match the pinned MIT release and integrity record.",
                        owned_paths=owned_paths,
                    )
                _guard_directories(root)
                _regular_file(entrypoint)
                version_check = runner(
                    [node, str(entrypoint), "--version"],
                    cwd=work,
                    timeout=30,
                    extra_env=environment,
                )
                if not version_check.succeeded or version_check.stdout.strip() != VERSION:
                    return RunnerOutcome(
                        status=OperationStatus.FAILED,
                        message="Installed promptfoo could not confirm its pinned CLI version.",
                        owned_paths=owned_paths,
                    )
                return RunnerOutcome(
                    status=OperationStatus.SUCCEEDED,
                    message=f"Verified promptfoo {VERSION}; "
                    + (
                        "reused the owned installation."
                        if already_installed
                        else "installed the pinned release."
                    ),
                    owned_paths=owned_paths,
                )
            _prepare_private_files(root)
            if step.step_id.endswith("-configure"):
                outcome = apply_json_edits(checked.configuration)
                return RunnerOutcome(
                    status=outcome.result.status,
                    message=outcome.result.message,
                    errors=outcome.result.errors,
                    configuration_ownership=[outcome.ownership]
                    if outcome.ownership is not None
                    else [],
                )
            _check_existing_configuration(
                root, load_record(str(root)), checked.configuration.relative_path
            )
            result_path = root / STATE_PREFIX / "results" / f"{checked.run_id}.json"
            descriptor = os.open(
                result_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
            )
            os.close(descriptor)
            command = [
                node,
                str(entrypoint),
                "eval",
                "--config",
                str(root / checked.configuration.relative_path),
                "--output",
                str(result_path),
                "--no-write",
                "--no-cache",
                "--no-share",
                "--no-progress-bar",
                "--no-table",
                "--max-concurrency",
                "1",
                "--env-file",
                str(root / STATE_PREFIX / "empty.env"),
            ]
            if checked.scenario == "fail":
                command.extend(["--var", "stackwinnowFail=true"])
            outcome = runner(
                command, cwd=work, timeout=120, extra_env=_environment(root, node, api_key=api_key)
            )
            try:
                evaluation = _summary(result_path, checked, outcome.returncode)
            except PromptfooError as exc:
                return RunnerOutcome(
                    status=OperationStatus.FAILED,
                    message=str(exc),
                    owned_paths=[str(result_path)],
                )
            except (OSError, ValueError, KeyError, TypeError):
                return RunnerOutcome(
                    status=OperationStatus.FAILED,
                    message="Evaluation did not produce a valid two-case report.",
                    owned_paths=[str(result_path)],
                )
            passed = (
                outcome.succeeded
                and checked.scenario == "pass"
                and evaluation.successes == 2
                and evaluation.failures == evaluation.errors == 0
            )
            message = f"Evaluation {'passed' if passed else 'failed'}: {evaluation.successes}/2 cases passed, {evaluation.failures} failed, {evaluation.errors} errored."
            if checked.scenario == "fail" and evaluation.successes == 2:
                message = "The negative control unexpectedly passed; verification is not accepted."
            return RunnerOutcome(
                status=OperationStatus.SUCCEEDED if passed else OperationStatus.FAILED,
                message=message,
                owned_paths=[str(result_path)],
                evidence=[EvidenceRef(source=str(result_path), detail=message)],
            )

        with _operation_lock(root):
            # Preflight runs without the lock. A competing apply may have finished
            # while it ran, so re-read receipts and configuration before any step.
            _validate_plan(root, checked)
            record, results = execute_plan(
                checked.installation,
                step_runner=run_step,
                configuration_intents={
                    checked.installation.steps[1].step_id: [checked.configuration]
                },
            )
        failures = [
            result
            for result in results
            if result.status in (OperationStatus.FAILED, OperationStatus.BLOCKED)
        ]
        if failures:
            status, message = failures[0].status, failures[0].message
        elif (
            evaluation is None
            or evaluation.process_returncode != 0
            or evaluation.successes != 2
            or evaluation.failures != 0
            or evaluation.errors != 0
            or checked.scenario != "pass"
            or not any(
                result.step_id == checked.installation.steps[-1].step_id
                and result.status == OperationStatus.SUCCEEDED
                for result in results
            )
        ):
            status = OperationStatus.BLOCKED
            message = "No fresh successful evaluation was recorded. Create a new plan."
        else:
            status = OperationStatus.SUCCEEDED
            message = "Promptfoo is installed, configured, and the evaluation passed."
        return PromptfooResult(
            plan=checked,
            status=status,
            message=message,
            results=results,
            record=record,
            evaluation=evaluation,
        )
    except (PromptfooError, ConfigurationError, InstallerError, OSError, ValidationError) as exc:
        message = (
            str(exc)
            if isinstance(exc, PromptfooError)
            else "Project state or configuration changed; inspect the managed receipts and create a new plan."
        )
        return blocked(message)

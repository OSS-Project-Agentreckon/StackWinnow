"""Offline adapter checks; the command double never installs packages or runs providers."""

from __future__ import annotations

import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from stackwinnow.adapters import headroom as adapter
from stackwinnow.adapters.headroom import (
    _FIXTURE_SHA256,
    _TOOL_ID,
    HeadroomError,
    HeadroomPlan,
    apply_headroom,
    plan_headroom,
)
from stackwinnow.contracts import OperationStatus
from stackwinnow.environments import python_env_path
from stackwinnow.installer import load_record


@pytest.fixture(autouse=True)
def declared_host(monkeypatch):
    """Portable adapter logic under host facts; no real macOS integration is claimed."""
    monkeypatch.setattr(adapter.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(adapter.platform, "machine", lambda: "arm64")


# ---------------------------------------------------------------------------
# Test double
# ---------------------------------------------------------------------------


@dataclass
class CommandResult:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0 and not self.timed_out


class FakeCommands:
    """Command runner that simulates venv creation, pip install, and compression."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Path, dict[str, str]]] = []
        self.venv_exit: int = 0
        self.ensurepip_exit: int = 0
        self.pip_exit: int = 0
        self.compress_exit: int = 0
        self.compress_output: dict | None = None  # None → valid default
        self.compress_timed_out: bool = False

    def __call__(
        self,
        args: list[str],
        *,
        cwd: str | Path,
        timeout: int,
        extra_env: dict[str, str] | None = None,
    ) -> CommandResult:
        assert isinstance(args, list)
        assert timeout > 0
        self.calls.append((args, Path(cwd), dict(extra_env or {})))

        # Normalise: strip -I inserted by _isolated_args so dispatch uses -m <module> form.
        effective = [a for a in args if a not in ("-I", "-B")]

        # --- python [-I] -m venv --without-pip <path> ---
        if len(effective) >= 3 and effective[1] == "-m" and effective[2] == "venv":
            venv_path = Path(effective[-1])
            if not self.venv_exit:
                _create_minimal_venv(venv_path)
            return CommandResult(returncode=self.venv_exit)

        # --- <venv>/bin/python [-I] -m ensurepip --upgrade ---
        if len(effective) >= 3 and effective[1] == "-m" and effective[2] == "ensurepip":
            return CommandResult(returncode=self.ensurepip_exit)

        # --- <venv>/bin/python [-I] -m pip install --quiet headroom-ai==VERSION ---
        if len(effective) >= 3 and effective[1] == "-m" and effective[2] == "pip":
            if not self.pip_exit:
                venv_path = _venv_from_python(args[0])
                _write_dist_info(venv_path)
            return CommandResult(
                returncode=self.pip_exit,
                stderr="" if not self.pip_exit else "synthetic pip failure",
            )

        if "-c" in args and args[-1].startswith("# stackwinnow-headroom-health"):
            return CommandResult(
                stdout=json.dumps(
                    {
                        "prefix": str(_venv_from_python(args[0])),
                        "version": adapter.VERSION,
                        "tokenizer": "o200k_base",
                        "distributions": [{"name": "headroom-ai", "version": adapter.VERSION}],
                    }
                )
            )

        # --- <venv>/bin/python -I -c <script> ---
        if "-c" in args and args[-1].startswith("# stackwinnow-headroom-compress"):
            if self.compress_timed_out:
                return CommandResult(returncode=-1, timed_out=True)
            if self.compress_exit:
                return CommandResult(
                    returncode=self.compress_exit,
                    stderr=json.dumps({"error": "synthetic compress failure"}),
                )
            run_line = next(
                line for line in args[-1].splitlines() if line.startswith("SW_RUN_ID = ")
            )
            default = {
                "messages_in": 2,
                "messages_out": 2,
                "tokens_before": 100,
                "tokens_after": 90,
                "tokens_saved": 10,
                "run_id": ast.literal_eval(run_line.split(" = ", 1)[1]),
                "fixture_sha256": adapter._FIXTURE_SHA256,
                "model_target": "gpt-4o",
                "tokenizer": "o200k_base",
                "system_preserved": True,
                "failure_preserved": True,
            }
            out = default | (self.compress_output or {})
            return CommandResult(stdout=json.dumps(out))

        raise AssertionError(f"Unexpected command: {args}")


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------


def _venv_from_python(python_exe: str) -> Path:
    """Infer venv root from <venv>/bin/python path."""
    return Path(python_exe).parent.parent


def _create_minimal_venv(venv_path: Path) -> None:
    py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    (venv_path / "bin").mkdir(parents=True, exist_ok=True)
    (venv_path / "lib" / py_ver / "site-packages").mkdir(parents=True, exist_ok=True)
    # Create the python symlink target so python_executable path exists
    (venv_path / "bin" / "python").touch(mode=0o755)


def _write_dist_info(venv_path: Path) -> None:
    py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    site = venv_path / "lib" / py_ver / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    dist_info = site / f"headroom_ai-{adapter.VERSION}.dist-info"
    dist_info.mkdir(exist_ok=True)
    (dist_info / "METADATA").write_text(
        f"Name: headroom-ai\nVersion: {adapter.VERSION}\nLicense: Apache-2.0\n"
    )


# ---------------------------------------------------------------------------
# plan_headroom tests
# ---------------------------------------------------------------------------


def test_plan_headroom_raises_when_not_in_catalog(fixture_project, monkeypatch):
    class _EmptyCatalog:
        def get(self, _tool_id):
            raise KeyError(_tool_id)

    monkeypatch.setattr(adapter, "load_catalog", lambda: _EmptyCatalog())
    with pytest.raises(HeadroomError, match="not in the tool catalog"):
        plan_headroom(fixture_project.root)


def test_plan_headroom_raises_when_license_not_reviewed(fixture_project, monkeypatch):
    from stackwinnow import catalog as cat_module

    catalog = cat_module.load_catalog()
    patched_tools = []
    for t in catalog.tools:
        if t.tool_id == "headroom":
            patched_tools.append(t.model_copy(update={"license_review": "pending"}, deep=True))
        else:
            patched_tools.append(t)
    patched = catalog.model_copy(update={"tools": tuple(patched_tools)}, deep=True)
    monkeypatch.setattr(adapter, "load_catalog", lambda: patched)
    with pytest.raises(HeadroomError, match="license review"):
        plan_headroom(fixture_project.root)


def test_plan_headroom_raises_when_venv_exists_without_ownership(fixture_project):
    # Create venv without an ownership receipt
    venv = python_env_path(str(fixture_project.root), _TOOL_ID)
    venv.mkdir(parents=True)
    with pytest.raises(HeadroomError, match="without an ownership receipt"):
        plan_headroom(fixture_project.root)


def test_plan_headroom_succeeds_on_clean_project(fixture_project):
    plan = plan_headroom(fixture_project.root)
    assert isinstance(plan, HeadroomPlan)
    assert plan.tool_id == "headroom"
    assert plan.version == adapter.VERSION
    assert plan.mode == "library"
    assert plan.fixture_sha256 == _FIXTURE_SHA256
    assert len(plan.installation.steps) == 2
    assert plan.installation.steps[0].step_id.endswith("-install")
    assert plan.installation.steps[1].step_id.endswith("-compress")


def test_plan_headroom_produces_unique_run_ids(fixture_project):
    p1 = plan_headroom(fixture_project.root)
    p2 = plan_headroom(fixture_project.root)
    assert p1.run_id != p2.run_id


# ---------------------------------------------------------------------------
# apply_headroom tests
# ---------------------------------------------------------------------------


def test_apply_headroom_dry_run_leaves_nothing_on_disk(fixture_project):
    plan = plan_headroom(fixture_project.root)
    result = apply_headroom(plan, dry_run=True)
    assert result.status == OperationStatus.SKIPPED
    assert result.dry_run is True
    venv = python_env_path(str(fixture_project.root), _TOOL_ID)
    assert not venv.exists()


def test_apply_headroom_blocked_when_no_runner(fixture_project, monkeypatch):
    monkeypatch.setattr(adapter, "_default_runner", lambda: None)
    plan = plan_headroom(fixture_project.root)
    result = apply_headroom(plan, command_runner=None)
    assert result.status == OperationStatus.BLOCKED
    assert any(
        kw in result.message.lower() for kw in ("runner", "unavailable", "unverified", "arm64")
    )


def test_apply_headroom_install_and_compress_succeed(fixture_project):
    runner = FakeCommands()
    plan = plan_headroom(fixture_project.root)
    result = apply_headroom(plan, command_runner=runner)

    assert result.status == OperationStatus.SUCCEEDED, result.message
    assert result.compression is not None
    assert result.compression.messages_in == 2
    assert result.compression.messages_out == 2
    assert result.compression.tokens_saved == 10
    # Verify venv ownership recorded
    record = load_record(str(fixture_project.root))
    venv = python_env_path(str(fixture_project.root), _TOOL_ID)
    assert any(str(venv) in receipt.owned_paths for receipt in record.steps)


def test_apply_headroom_venv_exit_failure(fixture_project):
    runner = FakeCommands()
    runner.venv_exit = 1
    plan = plan_headroom(fixture_project.root)
    result = apply_headroom(plan, command_runner=runner)
    assert result.status == OperationStatus.FAILED
    assert "venv creation" in result.message


def test_apply_headroom_pip_exit_failure(fixture_project):
    runner = FakeCommands()
    runner.pip_exit = 1
    plan = plan_headroom(fixture_project.root)
    result = apply_headroom(plan, command_runner=runner)
    assert result.status == OperationStatus.FAILED


def test_apply_headroom_compress_failure(fixture_project):
    runner = FakeCommands()
    runner.compress_exit = 1
    plan = plan_headroom(fixture_project.root)
    result = apply_headroom(plan, command_runner=runner)
    assert result.status == OperationStatus.FAILED
    assert "compress" in result.message.lower() or "failed" in result.message.lower()


def test_apply_headroom_compress_timeout(fixture_project):
    runner = FakeCommands()
    runner.compress_timed_out = True
    plan = plan_headroom(fixture_project.root)
    result = apply_headroom(plan, command_runner=runner)
    assert result.status == OperationStatus.FAILED
    assert "timed out" in result.message.lower()


def test_apply_headroom_compress_bad_json(fixture_project):
    class BadJsonRunner(FakeCommands):
        def __call__(self, args, *, cwd, timeout, extra_env=None):
            self.calls.append((args, Path(cwd), dict(extra_env or {})))
            if "-c" in args and args[-1].startswith("# stackwinnow-headroom-compress"):
                return CommandResult(stdout="NOT VALID JSON")
            return super().__call__(args, cwd=cwd, timeout=timeout, extra_env=extra_env)

    runner = BadJsonRunner()
    plan = plan_headroom(fixture_project.root)
    result = apply_headroom(plan, command_runner=runner)
    assert result.status == OperationStatus.FAILED
    assert "parse" in result.message.lower()


def test_apply_headroom_reuses_installed_venv(fixture_project):
    """Second apply with a NEW plan reuses the venv without reinstalling."""
    runner = FakeCommands()
    plan1 = plan_headroom(fixture_project.root)
    result1 = apply_headroom(plan1, command_runner=runner)
    assert result1.status == OperationStatus.SUCCEEDED

    install_calls_first = sum(1 for args, _, _ in runner.calls if "-m" in args and "pip" in args)

    plan2 = plan_headroom(fixture_project.root)
    result2 = apply_headroom(plan2, command_runner=runner)
    assert result2.status == OperationStatus.SUCCEEDED

    install_calls_total = sum(1 for args, _, _ in runner.calls if "-m" in args and "pip" in args)
    # pip install ran only once (the venv was reused on the second apply)
    assert install_calls_total == install_calls_first


def test_apply_headroom_plan_already_attempted_is_blocked(fixture_project):
    runner = FakeCommands()
    plan = plan_headroom(fixture_project.root)
    result1 = apply_headroom(plan, command_runner=runner)
    assert result1.status == OperationStatus.SUCCEEDED

    # Attempting to apply the SAME plan again should be blocked.
    result2 = apply_headroom(plan, command_runner=runner)
    assert result2.status == OperationStatus.BLOCKED
    assert "already attempted" in result2.message.lower()


# ---------------------------------------------------------------------------
# Regression tests for reviewer findings
# ---------------------------------------------------------------------------


def test_plan_raises_when_tool_dir_is_symlink(fixture_project, tmp_path):
    """Symlink at .stackwinnow/envs/headroom is rejected before any installation."""
    envs_dir = fixture_project.root / ".stackwinnow" / "envs"
    envs_dir.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    tool_dir = envs_dir / _TOOL_ID
    tool_dir.symlink_to(outside)
    with pytest.raises(HeadroomError, match="symlink"):
        plan_headroom(fixture_project.root)


def test_apply_raises_when_tool_dir_becomes_symlink_after_plan(fixture_project, tmp_path):
    """Symlink created between plan and apply is rejected at apply time."""
    plan = plan_headroom(fixture_project.root)
    # Create symlink after planning but before applying.
    envs_dir = fixture_project.root / ".stackwinnow" / "envs"
    envs_dir.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    tool_dir = envs_dir / _TOOL_ID
    tool_dir.symlink_to(outside)

    runner = FakeCommands()
    result = apply_headroom(plan, command_runner=runner)
    assert result.status == OperationStatus.BLOCKED
    assert "symlink" in result.message.lower()


def test_bootstrap_commands_carry_isolation_flag(fixture_project):
    """Every bootstrap/install command passes -I to avoid project-local module shadowing."""
    runner = FakeCommands()
    plan = plan_headroom(fixture_project.root)
    result = apply_headroom(plan, command_runner=runner)
    assert result.status == OperationStatus.SUCCEEDED

    for args, _cwd, _env in runner.calls:
        if "-c" in args:
            continue  # compress step is already -I -c
        if "-m" in args:
            m_pos = args.index("-m")
            assert m_pos >= 2 and args[m_pos - 1] == "-I", (
                f"Expected -I before -m in bootstrap command: {args}"
            )


def test_apply_blocked_on_zero_messages_out(fixture_project):
    """Compression claiming zero messages_out is rejected as invalid evidence."""
    runner = FakeCommands()
    runner.compress_output = {"messages_in": 2, "messages_out": 0, "tokens_saved": 10}
    plan = plan_headroom(fixture_project.root)
    result = apply_headroom(plan, command_runner=runner)
    assert result.status == OperationStatus.FAILED


def test_apply_blocked_on_negative_tokens_saved(fixture_project):
    """Negative tokens_saved is rejected as an invalid compression result."""
    runner = FakeCommands()
    runner.compress_output = {"messages_in": 2, "messages_out": 2, "tokens_saved": -50}
    plan = plan_headroom(fixture_project.root)
    result = apply_headroom(plan, command_runner=runner)
    assert result.status == OperationStatus.FAILED


def test_apply_blocked_on_mismatched_messages_in(fixture_project):
    """messages_in count not matching the fixture length is rejected."""
    runner = FakeCommands()
    runner.compress_output = {"messages_in": 999, "messages_out": 2, "tokens_saved": 10}
    plan = plan_headroom(fixture_project.root)
    result = apply_headroom(plan, command_runner=runner)
    assert result.status == OperationStatus.FAILED
    assert "mismatch" in result.message.lower()


def test_apply_blocked_when_catalog_becomes_unavailable_after_plan(fixture_project, monkeypatch):
    """Catalog unavailability after plan creation blocks apply."""
    from stackwinnow.catalog import CatalogError

    plan = plan_headroom(fixture_project.root)

    def raise_catalog_error():
        raise CatalogError("catalog unavailable")

    monkeypatch.setattr(adapter, "load_catalog", raise_catalog_error)
    runner = FakeCommands()
    result = apply_headroom(plan, command_runner=runner)
    assert result.status == OperationStatus.BLOCKED
    assert "catalog" in result.message.lower()


@pytest.mark.parametrize("system,machine", [("Linux", "aarch64"), ("Darwin", "x86_64")])
def test_unsupported_host_blocks_before_commands(fixture_project, monkeypatch, system, machine):
    monkeypatch.setattr(adapter.platform, "system", lambda: system)
    monkeypatch.setattr(adapter.platform, "machine", lambda: machine)
    runner = FakeCommands()
    result = apply_headroom(plan_headroom(fixture_project.root), command_runner=runner)
    assert result.status == OperationStatus.BLOCKED
    assert runner.calls == []
    assert not (fixture_project.root / ".stackwinnow").exists()

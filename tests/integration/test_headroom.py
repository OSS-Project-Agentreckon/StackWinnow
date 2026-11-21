"""Real pip installation and fixture compression; explicit opt-in only.

Requires --run-integration, Python 3.11+, pip, and internet access on first run
(tiktoken downloads vocab files from Azure CDN and caches them in the venv).
Subsequent runs reuse the cache.
"""

from __future__ import annotations

import platform

import pytest

from stackwinnow.adapters.headroom import (
    _TOOL_ID,
    apply_headroom,
    plan_headroom,
)
from stackwinnow.contracts import OperationStatus
from stackwinnow.environments import python_env_path
from stackwinnow.installer import load_record

pytestmark = pytest.mark.integration


@pytest.fixture
def real_runner():
    runner = None
    try:
        from stackwinnow.runner import run_command

        runner = run_command
    except ModuleNotFoundError:
        pass
    if runner is None:
        pytest.skip("The shared command runner is not available in this build.")
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        pytest.skip("Initial headroom acceptance requires macOS arm64.")
    return runner


def test_real_install_compress_and_reuse(fixture_project, real_runner):
    root = fixture_project.root.resolve()

    # First run: install and compress.
    plan1 = plan_headroom(root)
    result1 = apply_headroom(plan1, command_runner=real_runner)
    assert result1.status == OperationStatus.SUCCEEDED, result1.model_dump_json(indent=2)
    assert result1.compression is not None
    assert result1.compression.messages_in == 2
    assert result1.compression.messages_out >= 1

    venv = python_env_path(str(root), _TOOL_ID)
    assert venv.is_dir() and not venv.is_symlink()

    record1 = load_record(str(root))
    assert any(str(venv) in r.owned_paths for r in record1.steps)

    # Second run with a fresh plan: venv is reused; no reinstall.
    plan2 = plan_headroom(root)
    result2 = apply_headroom(plan2, command_runner=real_runner)
    assert result2.status == OperationStatus.SUCCEEDED, result2.model_dump_json(indent=2)
    assert result2.compression is not None

    record2 = load_record(str(root))
    # Four receipts: install+compress for each of the two plans
    assert len(record2.steps) == 4

    # Attempting the same plan a second time is blocked.
    result_replay = apply_headroom(plan2, command_runner=real_runner)
    assert result_replay.status == OperationStatus.BLOCKED
    assert "already attempted" in result_replay.message.lower()

"""Real pip installation and fixture compression; explicit opt-in only.

Requires --run-integration, Python 3.11+, pip, and internet access on first run
(tiktoken downloads vocab files from Azure CDN and caches them under .stackwinnow/headroom/cache).
Subsequent runs reuse the cache.
"""

from __future__ import annotations

import json
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
from stackwinnow.verify import check_project

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

    user_file = root / "keep.txt"
    user_file.write_text("User project data stays unchanged.")
    missing = check_project(root, tool_ids=["headroom"], run_functional=True)
    assert missing.status == "blocked"
    assert not (root / ".stackwinnow").exists()
    # First run: install and compress.
    plan1 = plan_headroom(root)
    assert apply_headroom(plan1, dry_run=True).status == "skipped"
    assert not (root / ".stackwinnow").exists()
    result1 = apply_headroom(plan1, command_runner=real_runner)
    assert result1.status == OperationStatus.SUCCEEDED, result1.model_dump_json(indent=2)
    assert result1.compression is not None
    assert result1.compression.messages_in == 2
    assert result1.compression.messages_out >= 1

    venv = python_env_path(str(root), _TOOL_ID)
    assert venv.is_dir() and not venv.is_symlink()

    record1 = load_record(str(root))
    assert any(str(venv) in r.owned_paths for r in record1.steps)

    passive = check_project(root, tool_ids=["headroom"])
    assert passive.status == "not_run"
    verified = check_project(root, tool_ids=["headroom"], run_functional=True)
    assert verified.ready, verified.model_dump_json(indent=2)
    negative = check_project(root, tool_ids=["headroom"], run_functional=True, scenario="fail")
    assert negative.status == "failed"
    # Second run with a fresh plan: venv is reused; no reinstall.
    plan2 = plan_headroom(root)
    result2 = apply_headroom(plan2, command_runner=real_runner)
    assert result2.status == OperationStatus.SUCCEEDED, result2.model_dump_json(indent=2)
    assert result2.compression is not None

    record2 = load_record(str(root))
    # Install/compress twice plus fresh verification and negative control.
    assert len(record2.steps) == 6
    assert user_file.read_text() == "User project data stays unchanged."
    (root / "acceptance-results.json").write_text(
        json.dumps(
            {
                "first": result1.model_dump(mode="json"),
                "second": result2.model_dump(mode="json"),
                "verification": verified.as_payload(),
                "negative": negative.as_payload(),
            },
            indent=2,
        )
    )

    # Attempting the same plan a second time is blocked.
    result_replay = apply_headroom(plan2, command_runner=real_runner)
    assert result_replay.status == OperationStatus.BLOCKED
    assert "already attempted" in result_replay.message.lower()

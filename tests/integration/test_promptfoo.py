"""Real pinned npm installation and evaluation; explicit opt-ins only."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
from pathlib import Path

import pytest

from stackwinnow.adapters.promptfoo import (
    NODE_PREFIX,
    _default_runner,
    apply_promptfoo,
    plan_promptfoo,
)
from stackwinnow.installer import load_record
from stackwinnow.verify import check_project

pytestmark = pytest.mark.integration


@pytest.fixture
def real_runner(tmp_path, subprocess_env):
    runner = _default_runner()
    if runner is None:
        pytest.skip("The shared command runner is not integrated in this build (PR #6).")
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        pytest.skip("Initial promptfoo acceptance requires macOS arm64.")
    node, npm = shutil.which("node"), shutil.which("npm")
    if node is None or npm is None:
        pytest.skip("Install Node 24 and npm to run promptfoo acceptance.")
    version = runner([node, "--version"], cwd=tmp_path, timeout=15, extra_env=subprocess_env)
    if not version.succeeded or not re.fullmatch(r"v24\.\d+\.\d+", version.stdout.strip()):
        pytest.skip("Initial promptfoo acceptance requires Node 24.")
    return runner


def test_real_onboarding_and_verification_pass_failure_repeat(fixture_project, real_runner):
    root = fixture_project.root.resolve()
    (root / "package.json").write_text('{"private":true,"name":"preserved-project"}\n')
    (root / ".npmrc").write_text("registry=http://127.0.0.1:9/do-not-read\n")
    # Promptfoo discovers cwd configs before its explicit --config argument.
    # This unrelated config must never be loaded by the adapter.
    (root / "promptfooconfig.js").write_text(
        "throw new Error('Unrelated project configuration was executed');\n"
    )
    preserved = {
        path: path.read_bytes()
        for path in (
            root / "package.json",
            root / ".npmrc",
            root / "promptfooconfig.js",
            fixture_project.settings,
        )
    }
    install_commands, commands = [], []

    def observe(args, **kwargs):
        commands.append(args)
        if "install" in args:
            install_commands.append(args)
        assert "OPENAI_API_KEY" not in (kwargs.get("extra_env") or {})
        return real_runner(args, **kwargs)

    positive = apply_promptfoo(plan_promptfoo(root), command_runner=observe)
    assert positive.status == "succeeded", positive.model_dump_json(indent=2)
    assert positive.evaluation.successes == 2
    assert positive.evaluation.failures == positive.evaluation.errors == 0
    assert positive.evaluation.process_returncode == 0
    config_bytes = (root / positive.plan.configuration.relative_path).read_bytes()
    negative = apply_promptfoo(plan_promptfoo(root, scenario="fail"), command_runner=observe)
    assert negative.status == "failed", negative.model_dump_json(indent=2)
    assert negative.evaluation.successes == negative.evaluation.errors == 0
    assert negative.evaluation.failures == 2 and negative.evaluation.process_returncode == 100
    repeat = apply_promptfoo(plan_promptfoo(root), command_runner=observe)
    assert repeat.status == "succeeded", repeat.model_dump_json(indent=2)
    assert repeat.evaluation.successes == 2
    assert len(install_commands) == 1
    assert (root / NODE_PREFIX / "node_modules/promptfoo/package.json").is_file()
    assert (root / positive.plan.configuration.relative_path).read_bytes() == config_bytes
    assert all(path.read_bytes() == original for path, original in preserved.items())
    assert len(load_record(str(root)).steps) == 9
    assert len({result.evaluation.result_path for result in (positive, negative, repeat)}) == 3
    for result in (positive, negative, repeat):
        data = json.loads(Path(result.evaluation.result_path).read_text())
        assert data.get("shareableUrl") is None
        assert data["results"]["stats"]["tokenUsage"]["total"] == 0

    # Stored onboarding evidence never substitutes for a fresh functional check.
    receipt_path = root / ".stackwinnow/receipts.json"
    configuration_path = root / positive.plan.configuration.relative_path
    stable_paths = [
        configuration_path,
        root / NODE_PREFIX / "node_modules/promptfoo/package.json",
        root / NODE_PREFIX / "node_modules/.package-lock.json",
    ]
    stable = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in stable_paths}
    receipt_before, calls_before = receipt_path.read_bytes(), list(commands)
    read_only = check_project(root, tool_ids=["promptfoo"], command_runner=observe)
    assert not read_only.ready and read_only.status == "not_run"
    assert receipt_path.read_bytes() == receipt_before and commands == calls_before
    checks = []
    for scenario in ("pass", "fail", "pass"):
        report = check_project(
            root,
            tool_ids=["promptfoo"],
            run_functional=True,
            scenario=scenario,
            command_runner=observe,
        )
        assert report.ready == (scenario == "pass"), report.model_dump_json(indent=2)
        states = {item.kind: item for item in report.tools[0].checks}
        assert states["installed"].status == states["configured"].status == "succeeded"
        assert states["connected"].status == "not_applicable"
        evidence = Path(states["functional"].evidence[0].source)
        data = json.loads(evidence.read_text())
        assert data["results"]["stats"]["successes"] == (2 if scenario == "pass" else 0)
        assert data["results"]["stats"]["failures"] == (0 if scenario == "pass" else 2)
        assert data["results"]["stats"]["errors"] == 0
        assert data["results"]["stats"]["tokenUsage"]["total"] == 0
        assert data.get("shareableUrl") is None
        checks.append(evidence)
    record = load_record(str(root))
    assert len(install_commands) == 1 and sum("eval" in args for args in commands) == 6
    assert len(record.steps) == 12
    assert all(step.step_id.endswith("-evaluate") for step in record.steps[-3:])
    assert [step.status for step in record.steps[-3:]] == ["succeeded", "failed", "succeeded"]
    assert record.steps[:9] == repeat.record.steps
    prior_reports = {Path(result.evaluation.result_path) for result in (positive, negative, repeat)}
    assert len(set(checks)) == 3 and set(checks).isdisjoint(prior_reports)
    assert all(
        (path.read_bytes(), path.stat().st_mtime_ns) == state for path, state in stable.items()
    )
    assert all(path.read_bytes() == original for path, original in preserved.items())


@pytest.mark.requires_provider
def test_optional_openai_evaluation(fixture_project, real_runner):
    model = os.environ.get("STACKWINNOW_PROMPTFOO_MODEL")
    if not model or not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("Explicit STACKWINNOW_PROMPTFOO_MODEL and OPENAI_API_KEY are required.")
    plan = plan_promptfoo(fixture_project.root, provider="openai", model=model)
    result = apply_promptfoo(plan, allow_provider_usage=True, command_runner=real_runner)
    assert result.status == "succeeded", result.message
    assert result.evaluation.successes == 2 and result.evaluation.process_returncode == 0

"""Opt-in real managed install with locked downloads, no model/provider usage."""

import platform

import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from stackwinnow.adapters.graphify import GraphifyError, RelationshipExpectation
from stackwinnow.adapters.graphify_install import INSTALL_ROOT, STEP_ID, apply_graphify_install
from stackwinnow.adapters.graphify_plan import ENV_PATH, plan_graphify_execution
from stackwinnow.runner import CommandResult, run_command

pytestmark = pytest.mark.integration


def test_real_graphify_managed_install_repeat_and_changed_state(fixture_project):
    if (
        platform.system() != "Darwin"
        or platform.machine() != "arm64"
        or not SpecifierSet(">=3.11.5,<3.12").contains(platform.python_version())
        or Version(platform.mac_ver()[0]) < Version("14")
    ):
        pytest.skip("Locked installation targets CPython 3.11.5–3.11.x / macOS 14+ arm64.")
    root = fixture_project.root.resolve()
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    plan = plan_graphify_execution(
        root,
        expectation=RelationshipExpectation(
            caller_file="sample_app/greetings.py",
            caller_label="greet()",
            callee_file="sample_app/names.py",
            callee_label="normalize_name()",
        ),
    )
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        result = run_command(argv, **kwargs)
        assert result.succeeded, result.stderr
        return result

    dry = apply_graphify_install(plan, dry_run=True, command_runner=runner)
    assert not dry.installed and not calls and not (root / ".stackwinnow").exists()
    installed = apply_graphify_install(plan, command_runner=runner)
    assert installed.installed, installed.model_dump_json()
    assert installed.record.receipt_for(STEP_ID).owned_paths == [INSTALL_ROOT]
    assert not installed.ready and len(calls) == 4
    again = apply_graphify_install(plan, command_runner=runner)
    assert again.installed and again.results[0].status == "skipped" and len(calls) == 4
    assert all((root / path).read_bytes() == raw for path, raw in before.items())
    assert not (root / ".codex").exists() and not (root / "AGENTS.md").exists()
    assert not (root / ".stackwinnow/graphify").exists()
    from stackwinnow.adapters.graphify_index import apply_graphify_index, plan_graphify_index
    from stackwinnow.verify import check_project

    index_plan = plan_graphify_index(root, expectation=plan.expectation)
    indexed = apply_graphify_index(index_plan, command_runner=runner)
    assert indexed.indexed, indexed.model_dump_json()
    assert len(calls) == 6  # install commands, extraction, upstream query
    repeated = apply_graphify_index(index_plan, command_runner=runner)
    assert repeated.indexed and repeated.results[0].status == "skipped" and len(calls) == 6
    reinstall = apply_graphify_install(plan, command_runner=runner)
    assert reinstall.installed and reinstall.results[0].status == "skipped" and len(calls) == 6
    verified = check_project(
        root, tool_ids=["graphify"], run_functional=True, command_runner=runner
    )
    observations = {item.kind: item for item in verified.tools[0].checks}
    assert observations["functional"].status == "succeeded", verified.as_payload()
    assert observations["connected"].status == "blocked" and not verified.ready
    assert len(calls) == 7
    changed = root / "sample_app/names.py"
    changed.write_text(changed.read_text() + "\n# deliberate source revision\n")
    with pytest.raises(GraphifyError, match="new index plan"):
        apply_graphify_index(index_plan, command_runner=runner)
    revised = plan_graphify_index(root, expectation=plan.expectation)
    assert apply_graphify_index(revised, command_runner=runner).indexed
    assert len(calls) == 9
    # Return the original reviewed source so the install-only negative control
    # below isolates runtime tampering, rather than the source-plan change.
    changed.write_bytes(before[changed.relative_to(root)])
    (root / ENV_PATH / "pyvenv.cfg").write_text("changed configuration\n")
    with pytest.raises(GraphifyError, match="installation changed"):
        apply_graphify_install(plan, command_runner=runner)
    assert len(calls) == 9

    # An actual venv/bootstrap followed by a controlled download failure retains
    # the partial directory and does not retry or delete it automatically.
    failed_root = root.parent / "failed-install"
    failed_root.mkdir()
    (failed_root / "source.py").write_text("def recur(): return recur()\n")
    failed_plan = plan_graphify_execution(
        failed_root,
        expectation=RelationshipExpectation(
            caller_file="source.py",
            caller_label="recur()",
            callee_file="source.py",
            callee_label="recur()",
        ),
    )

    def fail_download(argv, **kwargs):
        if "--require-hashes" in argv:
            return CommandResult(1, "", "controlled download failure")
        return run_command(argv, **kwargs)

    failed = apply_graphify_install(failed_plan, command_runner=fail_download)
    assert not failed.installed and failed.results[0].status == "failed"
    assert failed.record.receipt_for(STEP_ID).owned_paths == [INSTALL_ROOT]
    assert (failed_root / ENV_PATH / "bin/python").is_file()
    with pytest.raises(GraphifyError, match="manual inspection"):
        apply_graphify_install(failed_plan, command_runner=fail_download)

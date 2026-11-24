"""Workflow composition uses real adapters/files with declared command doubles."""

import json
import sys
import tomllib
from pathlib import Path

import pytest
from promptfoo_fakes import FakeCommands as PromptfooCommands
from pydantic import ValidationError
from test_graphify_index_adapter import EXPECTATION, FakeIndex, _fake_graph
from test_graphify_install_adapter import FakeInstall
from test_headroom_adapter import FakeCommands as HeadroomCommands
from test_playwright_adapter import Runner as PlaywrightCommands

from stackwinnow import workflow as api
from stackwinnow.adapters import graphify_plan, headroom, playwright_mcp, promptfoo
from stackwinnow.adapters._managed import record_for
from stackwinnow.adapters.graphify_index import inspect_graphify_index
from stackwinnow.cli import main
from stackwinnow.contracts import EvidenceRef
from stackwinnow.installer import ExecutionRecord, StepReceipt, _persist
from stackwinnow.runner import CommandResult
from stackwinnow.supported import ToolSelection, select_tool
from stackwinnow.verify import CheckKind, ToolVerification, VerificationCheck, VerificationReport
from stackwinnow.workflow_state import WorkflowError


def request(*ids, expectation=None):
    return api.WorkflowRequest(
        selections=tuple(select_tool(name) for name in ids), expectation=expectation
    )


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "caller.py").write_text("from callee import answer\ndef call(): return answer()\n")
    (root / "callee.py").write_text("def answer(): return 42\n")
    bins = tmp_path / "bin"
    bins.mkdir()
    for name in ("node", "npm", "codex"):
        path = bins / name
        path.write_text("declared command double")
        path.chmod(0o700)
    monkeypatch.setattr(promptfoo.shutil, "which", lambda name: str(bins / name))
    monkeypatch.setattr(headroom.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(headroom.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(headroom.platform, "python_implementation", lambda: "CPython")
    monkeypatch.setattr(headroom.platform, "python_version", lambda: "3.11.14")
    monkeypatch.setattr(headroom.platform, "mac_ver", lambda: ("14.0", (), "arm64"))
    monkeypatch.setattr(
        graphify_plan,
        "_runtime",
        lambda: graphify_plan.RuntimeSnapshot(
            executable=sys.executable,
            implementation="CPython",
            version="3.11.14",
            system="Darwin",
            machine="arm64",
            macos_version="14.0",
        ),
    )
    return root


class Commands:
    def __init__(self, root):
        self.calls = []
        self.headroom = HeadroomCommands()
        self.promptfoo = PromptfooCommands()
        self.playwright = PlaywrightCommands(root)
        self.install = FakeInstall()
        self.index = FakeIndex(graph_factory=lambda staged: _fake_graph(staged, EXPECTATION))
        self.bad_version = None

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        name = Path(args[0]).name
        if len(args) == 2 and args[-1] == "--version":
            output = {"node": "v24.13.1", "npm": "11.0.0", "codex": "codex-cli 0.169.0"}[name]
            return CommandResult(0, "wrong" if self.bad_version == name else output, "")
        joined = " ".join(args)
        if "headroom" in joined:
            return self.headroom(args, **kwargs)
        if "promptfoo" in joined or "promptfoo" in str(kwargs["cwd"]):
            translated = list(args)
            if name in ("node", "npm"):
                translated[0] = "/declared/" + name
            return self.promptfoo(translated, **kwargs)
        if "playwright" in joined:
            return self.playwright(args, **kwargs)
        if "extract" in args or "--graph" in args:
            return self.index(args, **kwargs)
        return self.install(args, **kwargs)


@pytest.fixture
def client(monkeypatch):
    def check(root, registration, codex, **kwargs):
        return {
            "connected": True,
            "functional": True,
            "message": "Offline client double.",
            "evidence_path": str(root / ".stackwinnow/client-double.json"),
        }

    monkeypatch.setattr("stackwinnow.verify.playwright_client.run_client_check", check)
    monkeypatch.setattr("stackwinnow.verify.playwright_mcp.run_client_check", check)


def graph_report(root, *, tool_ids, run_functional=False, **kwargs):
    """Only the terminal client check is doubled in Graphify composition tests."""
    return VerificationReport(
        project_root=str(root),
        checked_at="2026-11-23",
        run_functional=run_functional,
        tools=tuple(
            ToolVerification(
                tool_id=name,
                connection_scope="assistant",
                checks=tuple(
                    VerificationCheck(
                        kind=kind,
                        status="succeeded"
                        if run_functional or kind != CheckKind.FUNCTIONAL
                        else "not_run",
                        code="workflow-command-double",
                        message="Composition test evidence only.",
                        evidence=(
                            EvidenceRef(
                                source="test-double", detail="Not an upstream integration claim"
                            ),
                        ),
                    )
                    for kind in CheckKind
                ),
            )
            for name in tool_ids
        ),
    )


def test_preview_dry_run_cancel_are_pure(project):
    before = {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}
    plan = api.plan_workflow(
        project,
        request("headroom", "promptfoo", "playwright-mcp", "graphify", expectation=EXPECTATION),
    )
    commands = Commands(project)
    result = api.apply_workflow(plan, dry_run=True, command_runner=commands)
    assert result.dry_run and not result.ready and not commands.calls
    assert not (project / ".stackwinnow").exists()
    assert before == {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}
    assert plan.phases == [
        "graphify-runtime",
        "headroom",
        "promptfoo",
        "playwright-mcp",
        "graphify-index",
        "graphify-configure",
        "verify",
    ]


@pytest.mark.parametrize(
    "selection",
    [
        {"tool_id": "aider", "mode": "library", "version": "1"},
        {"tool_id": "headroom", "mode": "proxy", "version": headroom.VERSION},
        {"tool_id": "headroom", "mode": "library", "version": "latest"},
    ],
)
def test_only_actual_supported_modes_selectable(selection):
    with pytest.raises(ValidationError, match="Unsupported"):
        ToolSelection(**selection)


@pytest.mark.parametrize(
    "ids,expectation",
    [(("headroom", "headroom"), None), (("graphify",), None), (("headroom",), EXPECTATION)],
)
def test_invalid_selection_constraints(ids, expectation):
    with pytest.raises(ValidationError):
        request(*ids, expectation=expectation)


@pytest.mark.parametrize("change", ["manifest", "config", "sources", "executable", "receipt"])
def test_changed_inputs_block_before_mutation(project, change):
    plan = api.plan_workflow(project, request("graphify", expectation=EXPECTATION))
    if change == "manifest":
        (project / "pyproject.toml").write_text("[project]\nname='changed'\n")
    elif change == "config":
        (project / ".codex").mkdir()
        (project / ".codex/config.toml").write_text("# new setting\n")
    elif change == "sources":
        (project / "unrelated.py").write_text("changed = True\n")
    elif change == "executable":
        Path(plan.state.executables["codex"].path).write_text("changed executable")
    else:
        (project / ".stackwinnow").mkdir()
        _persist(
            ExecutionRecord(
                project_root=str(project),
                steps=[
                    StepReceipt(
                        step_id="foreign",
                        tool_id="headroom",
                        status="succeeded",
                        message="foreign",
                        timestamp="now",
                    )
                ],
            ),
            project_root=str(project),
        )
    commands = Commands(project)
    with pytest.raises(WorkflowError, match="changed"):
        api.apply_workflow(plan, command_runner=commands)
    assert not commands.calls
    assert not (project / ".stackwinnow/workflows").exists()


@pytest.mark.parametrize("field", ["leaf", "selection", "provider", "recipe", "extra"])
def test_forged_plan_rejected_even_with_recomputed_checksum(project, field):
    plan = api.plan_workflow(project, request("promptfoo"))
    data = plan.model_dump()
    if field == "extra":
        data["commands"] = ["do-something"]
        with pytest.raises(ValidationError):
            api.WorkflowPlan.model_validate(data)
        return
    if field == "leaf":
        plan.promptfoo.installation.steps[0].description = "unreviewed step"
    elif field == "selection":
        plan.request = request("headroom")
    elif field == "provider":
        plan.promptfoo = promptfoo.plan_promptfoo(project, provider="openai", model="gpt-4o-mini")
    else:
        plan.recipe_sha256 = "0" * 64
    plan.checksum = api._checksum(plan)
    commands = Commands(project)
    with pytest.raises((ValueError, RuntimeError)):
        api.apply_workflow(plan, command_runner=commands)
    assert not commands.calls and not (project / ".stackwinnow").exists()


@pytest.mark.parametrize("name", ["node", "npm", "codex"])
def test_all_prerequisites_checked_before_first_install(project, name):
    plan = api.plan_workflow(
        project, request("graphify", "promptfoo", "playwright-mcp", expectation=EXPECTATION)
    )
    commands = Commands(project)
    commands.bad_version = name
    with pytest.raises(WorkflowError, match="version"):
        api.apply_workflow(plan, command_runner=commands)
    assert all(args[-1] == "--version" for args in commands.calls)
    assert not (project / ".stackwinnow").exists()


@pytest.mark.parametrize("tool", ["headroom", "promptfoo", "playwright-mcp"])
def test_fresh_apply_repeat_and_passive_status(project, client, tool):
    commands = Commands(project)
    for _ in range(2):
        plan = api.plan_workflow(project, request(tool))
        result = api.apply_workflow(plan, command_runner=commands)
        assert result.ready, result.as_payload()
        assert result.verification.run_functional
        assert not result.passive_status.run_functional and not result.passive_status.ready
        assert (project / api._journal_path(plan)).is_file()
        with pytest.raises(WorkflowError):
            api.apply_workflow(plan, command_runner=commands)
    if tool != "headroom":
        receipt = record_for(project).receipt_for(
            getattr(plan, "playwright" if tool == "playwright-mcp" else tool)
            .installation.steps[1]
            .step_id
        )
        assert receipt.status == "skipped"  # valid no-op, fresh verification still ran


def test_graphify_composes_source_and_codex_effects(project, client, monkeypatch):
    (project / ".codex").mkdir()
    original = b"# preserve this user comment\nmodel = 'user-model'\n"
    (project / ".codex/config.toml").write_bytes(original)
    monkeypatch.setattr(api, "check_project", graph_report)
    commands = Commands(project)
    selected = request("promptfoo", "playwright-mcp", "graphify", expectation=EXPECTATION)
    first = api.plan_workflow(project, selected)
    result = api.apply_workflow(first, command_runner=commands)
    assert result.ready, result.as_payload()
    provenance, _ = inspect_graphify_index(project)
    assert {s.path: s.sha256 for s in provenance.plan.sources}[
        "promptfooconfig.stackwinnow.json"
    ] == first.promptfoo.configuration.written_file.sha256
    settings = (project / ".codex/config.toml").read_bytes()
    assert settings.startswith(original)
    assert set(tomllib.loads(settings.decode())["mcp_servers"]) == {
        "stackwinnow_graphify",
        "stackwinnow_playwright",
    }
    (project / "new.py").write_text("# deliberately reviewed next index\n")
    second = api.plan_workflow(project, selected)
    assert second.graphify_reuse and second.graphify == first.graphify
    repeated = api.apply_workflow(second, command_runner=commands)
    assert repeated.ready, repeated.as_payload()
    assert "new.py" in {s.path for s in inspect_graphify_index(project)[0].plan.sources}


def test_failure_preserves_partial_state_and_stops_next_tool(project):
    commands = Commands(project)
    commands.promptfoo.install_exit = 1
    plan = api.plan_workflow(project, request("headroom", "promptfoo", "playwright-mcp"))
    result = api.apply_workflow(plan, command_runner=commands)
    assert result.stopped_phase == "promptfoo" and not result.ready
    assert result.as_payload()["partial_completion"]
    assert not (project / playwright_mcp.STATE).exists()
    assert any(
        s.tool_id == "headroom" and s.status == "succeeded" for s in record_for(project).steps
    )
    assert any(s.tool_id == "promptfoo" and s.status == "failed" for s in record_for(project).steps)


def test_changes_after_success_are_not_adopted(project, monkeypatch):
    plan = api.plan_workflow(project, request("headroom", "promptfoo"))
    original = headroom.apply_headroom

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        if not kwargs.get("dry_run"):
            (project / "package.json").write_text('{"foreign":true}')
        return result

    monkeypatch.setattr(headroom, "apply_headroom", changed)
    result = api.apply_workflow(plan, command_runner=Commands(project))
    assert result.stopped_phase == "headroom" and not result.ready
    assert not any(s.tool_id == "promptfoo" for s in record_for(project).steps)


def test_change_between_check_and_adapter_lock_blocks_before_write(project, monkeypatch):
    plan = api.plan_workflow(project, request("headroom"))
    original = headroom.apply_headroom

    def concurrent(leaf, **kwargs):
        if not kwargs.get("dry_run"):
            (project / "package.json").write_text('{"concurrent":true}')
        return original(leaf, **kwargs)

    monkeypatch.setattr(headroom, "apply_headroom", concurrent)
    result = api.apply_workflow(plan, command_runner=Commands(project))
    assert not result.ready and result.stopped_phase == "headroom"
    assert not record_for(project).steps


def test_cli_modes_plan_dry_run_and_validation(project, tmp_path, capsys):
    assert main(["workflow", "modes", "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)["modes"]) == 23
    assert main(["workflow", "plan", str(project), "--tool", "headroom", "--json"]) == 0
    saved = tmp_path / "workflow.json"
    saved.write_text(capsys.readouterr().out)
    assert main(["workflow", "apply", str(saved), "--dry-run", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"]
    with pytest.raises(SystemExit) as exc:
        main(["workflow", "plan", str(project), "--tool", "aider"])
    assert exc.value.code == 2
    assert not (project / ".stackwinnow").exists()


@pytest.mark.parametrize("mutation", ["change-install", "delete-config", "new-install"])
def test_terminal_verification_preserves_selected_ownership(project, monkeypatch, mutation):
    original = api.check_project

    def check(root, **kwargs):
        report = original(root, **kwargs)
        if kwargs.get("run_functional"):
            record = record_for(root)
            if mutation == "change-install":
                record.steps[0].message = "concurrent overwrite"
            elif mutation == "delete-config":
                record.steps = [s for s in record.steps if not s.step_id.endswith("-configure")]
            else:
                record.steps.append(
                    StepReceipt(
                        step_id="headroom-unexpected-install",
                        tool_id="headroom",
                        status="succeeded",
                        message="unexpected new installation",
                        timestamp="now",
                    )
                )
            _persist(record, project_root=str(root))
        return report

    monkeypatch.setattr(api, "check_project", check)
    result = api.apply_workflow(
        api.plan_workflow(project, request("promptfoo")), command_runner=Commands(project)
    )
    assert not result.ready and result.stopped_phase == "verify", result.as_payload()
    assert any("receipt" in p.message or "ownership" in p.message for p in result.outcomes)


def test_final_passive_runtime_failure_prevents_ready(project, monkeypatch):
    original = api.check_project

    def check(root, **kwargs):
        if not kwargs.get("run_functional"):
            (root / ".stackwinnow/envs/headroom/python/bin/python").write_text("runtime replaced")
        return original(root, **kwargs)

    monkeypatch.setattr(api, "check_project", check)
    result = api.apply_workflow(
        api.plan_workflow(project, request("headroom")), command_runner=Commands(project)
    )
    assert result.verification.ready
    assert not result.ready and result.stopped_phase == "status"
    assert result.as_payload()["status"] == "blocked"


def test_new_graphify_relationship_keeps_original_install_recipe(project, monkeypatch):
    monkeypatch.setattr(api, "check_project", graph_report)
    first = api.plan_workflow(project, request("graphify", expectation=EXPECTATION))
    commands = Commands(project)
    assert api.apply_workflow(first, command_runner=commands).ready
    newer = EXPECTATION.model_copy(update={"caller_label": "new_call()"})
    (project / "caller.py").write_text(
        "from callee import answer\ndef new_call(): return answer()\n"
    )
    commands.index = FakeIndex(graph_factory=lambda staged: _fake_graph(staged, newer))
    second = api.plan_workflow(project, request("graphify", expectation=newer))
    assert (
        second.graphify == first.graphify
        and second.request.expectation != second.graphify.expectation
    )
    result = api.apply_workflow(second, command_runner=commands)
    assert result.ready, result.as_payload()
    assert inspect_graphify_index(project)[0].plan.expectation == newer


def test_duplicate_plan_json_keys_rejected_before_apply(project, tmp_path):
    plan = api.plan_workflow(project, request("headroom"))
    saved = tmp_path / "duplicate.json"
    saved.write_text('{"schema_version":1,' + plan.model_dump_json()[1:])
    with pytest.raises(WorkflowError, match="Invalid workflow plan"):
        api.load_workflow_plan(saved)
    assert not (project / ".stackwinnow").exists()


@pytest.mark.parametrize("local_check", [False, True])
def test_real_graphify_verifier_path_keeps_setup_receipts(project, monkeypatch, local_check):
    from stackwinnow.verify.graphify import VERIFY_STEP_ID, _check_local
    from stackwinnow.verify.models import VerificationOptions

    commands = Commands(project)

    def client(root, settings, expected, **kwargs):
        # The production Codex branch normally emits only its client receipt.
        # A concurrent narrow check in this interval must not be silently
        # adopted as part of the expected client transition.
        if local_check:
            _check_local(
                root,
                VerificationOptions(tool_ids=["graphify"], run_functional=True),
                command_runner=commands,
            )
        return {"connected": True, "functional": True, "calls": [], "provider": "test-double"}

    monkeypatch.setattr("stackwinnow.verify.graphify_client.run_client_check", client)
    for _ in range(2):
        plan = api.plan_workflow(project, request("graphify", expectation=EXPECTATION))
        result = api.apply_workflow(plan, command_runner=commands)
        if local_check:
            assert not result.ready and result.stopped_phase == "verify", result.as_payload()
            return
        assert result.ready, result.as_payload()
        assert result.verification.ready and not result.passive_status.ready
        assert record_for(project).receipt_for(VERIFY_STEP_ID) is None


def test_passive_inspection_cannot_hide_a_concurrent_receipt_change(project, monkeypatch):
    original = api.check_project

    def check(root, **kwargs):
        report = original(root, **kwargs)
        if not kwargs.get("run_functional"):
            record = record_for(root)
            record.steps = [s for s in record.steps if not s.step_id.endswith("-configure")]
            _persist(record, project_root=str(root))
        return report

    monkeypatch.setattr(api, "check_project", check)
    result = api.apply_workflow(
        api.plan_workflow(project, request("promptfoo")), command_runner=Commands(project)
    )
    assert result.verification.ready
    assert not result.ready and result.stopped_phase == "status"
    assert "changed" in result.outcomes[-1].message

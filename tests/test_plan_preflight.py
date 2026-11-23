"""Offline preliminary checks: no receipt, directory or PATH shortcut grants readiness."""

import json

import pytest

from stackwinnow.catalog import EligibilityContext, Platform, load_catalog
from stackwinnow.contracts import InstallPlan, IntegrationAvailability, OperationStatus, PlanStep
from stackwinnow.plan import (
    PreflightCheck,
    PreflightError,
    PreflightReport,
    PreflightStatus,
    _find_external_executable,
    check_plan,
)


@pytest.fixture(autouse=True)
def declared_host(monkeypatch):
    """Exercise portable logic under explicit host facts, never actual upstream commands."""
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("platform.machine", lambda: "arm64")
    monkeypatch.setattr("platform.python_implementation", lambda: "CPython")
    monkeypatch.setattr("platform.python_version", lambda: "3.11.8")
    monkeypatch.setattr("platform.mac_ver", lambda: ("14.7", (), "arm64"))
    monkeypatch.setattr("shutil.which", lambda name: None)

    def no_command(*args, **kwargs):
        pytest.fail("Preflight must never execute commands.")

    monkeypatch.setattr("subprocess.run", no_command)
    monkeypatch.setattr("subprocess.Popen", no_command)


def plan(root, *tools):
    tools = tools or ("headroom",)
    return InstallPlan(
        project_root=str(root),
        assistant="codex",
        tool_ids=list(tools),
        steps=[
            PlanStep(step_id=f"install-{t}", tool_id=t, description=f"Install {t}") for t in tools
        ],
    )


def eligible(*tools):
    """Supply catalog/prerequisite evidence independently from real mode support."""
    catalog = load_catalog()
    entries = tuple(
        t.model_copy(
            update={
                "availability": IntegrationAvailability.ADAPTER_AVAILABLE,
                "supported_platforms": [Platform.MACOS],
                "supported_assistants": ["codex"],
            }
        )
        if t.tool_id in tools
        else t
        for t in catalog.tools
    )
    return {
        "catalog": catalog.model_copy(update={"tools": entries}),
        "context": EligibilityContext(
            platform=Platform.MACOS,
            assistant="codex",
            registered_adapters=list(tools),
            prerequisite_checks={t: OperationStatus.SUCCEEDED for t in tools},
        ),
    }


def receipt(root, *, tool="headroom", status="succeeded", step="install-headroom", dry_run=False):
    state = root / ".stackwinnow"
    state.mkdir(exist_ok=True)
    path = state / "receipts.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_root": str(root),
                "steps": [
                    {
                        "schema_version": 1,
                        "step_id": step,
                        "tool_id": tool,
                        "status": status,
                        "message": "Past operation",
                        "timestamp": "2026-11-19T00:00:00+00:00",
                        "dry_run": dry_run,
                    }
                ],
            }
        )
    )
    return path


def snapshot(root):
    return {
        str(p.relative_to(root)): p.read_bytes() if p.is_file() else None for p in root.rglob("*")
    }


@pytest.mark.parametrize("status", list(PreflightStatus))
def test_only_explicit_ready_checks_grant_preliminary_readiness(tmp_path, status):
    report = PreflightReport(
        project_root=str(tmp_path),
        checks=[
            PreflightCheck(
                step_id="install-headroom",
                tool_id="headroom",
                status=status,
                message="Observation",
            )
        ],
    )
    assert report.is_ready_to_apply == (status == PreflightStatus.READY)
    assert bool(report.blocked_checks) == (status == PreflightStatus.BLOCKED)
    assert PreflightReport.model_validate_json(report.model_dump_json()) == report


def test_empty_plan_is_not_actionable(tmp_path):
    report = check_plan(InstallPlan(project_root=str(tmp_path), tool_ids=[], steps=[]))
    assert report.checks == [] and not report.is_ready_to_apply
    assert list(tmp_path.iterdir()) == []


def test_fresh_eligible_plan_has_only_preliminary_readiness_and_is_pure(tmp_path):
    before = snapshot(tmp_path)
    report = check_plan(
        plan(tmp_path, "headroom", "promptfoo"), **eligible("headroom", "promptfoo")
    )
    assert report.is_ready_to_apply
    assert [c.step_id for c in report.checks] == ["install-headroom", "install-promptfoo"]
    assert all("preliminary" in c.message for c in report.checks)
    assert all("workflow plan" in c.reasons[0] for c in report.checks)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize(
    "override",
    [
        {"platform": None},
        {"platform": Platform.LINUX},
        {"assistant": None},
        {"prerequisite_checks": {}},
        {"prerequisite_checks": {"headroom": OperationStatus.FAILED}},
        {"registered_adapters": []},
    ],
)
@pytest.mark.parametrize("existing", ["receipt", "external"])
def test_existing_observations_never_bypass_eligibility(tmp_path, monkeypatch, override, existing):
    args = eligible("headroom")
    args["context"] = args["context"].model_copy(update=override)
    if existing == "receipt":
        receipt(tmp_path)
        (tmp_path / ".stackwinnow/envs/headroom/python").mkdir(parents=True)
    else:
        monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/headroom")
    before = snapshot(tmp_path)
    report = check_plan(plan(tmp_path), **args)
    assert report.checks[0].status == "blocked" and not report.is_ready_to_apply
    assert "eligible" in report.checks[0].message
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize(
    "change",
    [
        {"license_review": "unresolved"},
        {"availability": IntegrationAvailability.CATALOG_ONLY},
    ],
)
def test_license_and_catalog_gates_survive_external_presence(tmp_path, monkeypatch, change):
    args = eligible("headroom")
    cat = args["catalog"]
    args["catalog"] = cat.model_copy(
        update={
            "tools": tuple(
                t.model_copy(update=change) if t.tool_id == "headroom" else t for t in cat.tools
            )
        }
    )
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/headroom")
    assert not check_plan(plan(tmp_path), **args).is_ready_to_apply


@pytest.mark.parametrize("tool", ["serena", "unknown-tool"])
def test_registry_cannot_be_invented_by_context_or_path(tmp_path, monkeypatch, tool):
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/local/bin/{name}")
    report = check_plan(plan(tmp_path, tool), **eligible(tool))
    assert report.checks[0].status == "blocked"
    assert not report.is_ready_to_apply


@pytest.mark.parametrize(
    "fact,value,tool",
    [
        ("system", "Linux", "headroom"),
        ("machine", "x86_64", "promptfoo"),
        ("python_version", "3.14.0", "graphify"),
        ("python_implementation", "PyPy", "graphify"),
    ],
)
def test_real_supported_host_gates_cannot_be_bypassed_by_target_context(
    tmp_path, monkeypatch, fact, value, tool
):
    monkeypatch.setattr(f"platform.{fact}", lambda: value)
    report = check_plan(plan(tmp_path, tool), **eligible(tool))
    assert not report.is_ready_to_apply and "host" in report.checks[0].message


@pytest.mark.parametrize("status", ["succeeded", "failed", "blocked", "skipped"])
@pytest.mark.parametrize("step", ["install-headroom", "verify-headroom", "remove-headroom"])
@pytest.mark.parametrize("environment", [False, True])
def test_any_tool_history_requires_recipe_review_without_claiming_ownership(
    tmp_path, status, step, environment
):
    receipt(tmp_path, status=status, step=step)
    if environment:
        (tmp_path / ".stackwinnow/envs/headroom/python").mkdir(parents=True)
    before = snapshot(tmp_path)
    report = check_plan(plan(tmp_path), **eligible("headroom"))
    assert report.checks[0].status == "blocked" and not report.is_ready_to_apply
    assert "workflow review" in report.checks[0].message
    advice = " ".join(report.checks[0].reasons)
    assert "preserve receipts" in advice and "clear the receipt" not in advice
    assert snapshot(tmp_path) == before


def test_dry_run_receipt_does_not_establish_existing_installation(tmp_path):
    receipt(tmp_path, dry_run=True)
    assert check_plan(plan(tmp_path), **eligible("headroom")).is_ready_to_apply


@pytest.mark.parametrize("relative", ["headroom", "headroom/python", "headroom/node"])
def test_empty_environment_requires_review_even_without_receipts(tmp_path, relative):
    (tmp_path / ".stackwinnow/envs" / relative).mkdir(parents=True)
    report = check_plan(plan(tmp_path), **eligible("headroom"))
    assert not report.is_ready_to_apply and "workflow review" in report.checks[0].message


@pytest.mark.parametrize(
    "relative",
    [
        ".stackwinnow",
        ".stackwinnow/envs",
        ".stackwinnow/envs/headroom",
        ".stackwinnow/envs/headroom/python",
        ".stackwinnow/envs/headroom/node",
    ],
)
@pytest.mark.parametrize("kind", ["symlink", "file"])
def test_unsafe_environment_ancestors_rejected_even_when_context_is_ineligible(
    tmp_path, relative, kind
):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "symlink":
        target = tmp_path / "outside"
        target.mkdir()
        (target / "python").mkdir()
        path.symlink_to(target)
    else:
        path.write_text("occupied")
    with pytest.raises(PreflightError, match="real directories"):
        check_plan(plan(tmp_path))


@pytest.mark.parametrize(
    "problem",
    [
        "invalid-json",
        "duplicate-key",
        "duplicate-step",
        "other-project",
        "oversize",
        "symlink",
        "hardlink",
        "fifo",
    ],
)
def test_receipts_are_bounded_unambiguous_and_preserved(tmp_path, problem):
    path = receipt(tmp_path)
    raw = path.read_text()
    if problem == "invalid-json":
        path.write_text("{")
    elif problem == "duplicate-key":
        path.write_text('{"schema_version":1,' + raw[1:])
    elif problem == "duplicate-step":
        data = json.loads(raw)
        data["steps"] *= 2
        path.write_text(json.dumps(data))
    elif problem == "other-project":
        data = json.loads(raw)
        data["project_root"] = str(tmp_path / "other")
        path.write_text(json.dumps(data))
    elif problem == "oversize":
        path.write_text(" " * (4 * 1024 * 1024 + 1))
    else:
        path.unlink()
        target = tmp_path / "outside.json"
        target.write_text(raw)
        if problem == "symlink":
            path.symlink_to(target)
        elif problem == "hardlink":
            path.hardlink_to(target)
        else:
            import os

            os.mkfifo(path)
    before = path.lstat()
    with pytest.raises(PreflightError):
        check_plan(plan(tmp_path), **eligible("headroom"))
    after = path.lstat()
    assert (before.st_ino, before.st_size, before.st_mtime_ns) == (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )


def test_external_path_is_observation_not_readiness(tmp_path, monkeypatch):
    external = "/usr/local/bin/headroom"
    monkeypatch.setattr("shutil.which", lambda name: external)
    report = check_plan(plan(tmp_path), **eligible("headroom"))
    check = report.checks[0]
    assert check.status == "external-install-detected" and check.external_path == external
    assert not report.is_ready_to_apply and external in check.message


@pytest.mark.parametrize(
    "location,external",
    [
        (".stackwinnow/envs/headroom/bin/tool", False),
        (".stackwinnow-backup/bin/tool", True),
        ("user-bin/tool", True),
    ],
)
def test_external_path_detection_uses_path_boundaries(tmp_path, monkeypatch, location, external):
    path = str(tmp_path / location)
    monkeypatch.setattr("shutil.which", lambda name: path)
    assert _find_external_executable(str(tmp_path), "headroom") == (path if external else None)


def test_history_is_tool_specific_and_steps_are_independent(tmp_path):
    receipt(tmp_path, tool="promptfoo", step="install-headroom")
    report = check_plan(
        plan(tmp_path, "promptfoo", "headroom", "unknown-tool"), **eligible("promptfoo", "headroom")
    )
    assert [c.status for c in report.checks] == ["blocked", "ready", "blocked"]
    assert len(report.blocked_checks) == 2 and not report.is_ready_to_apply


@pytest.mark.parametrize("tool", ["graphify", "playwright-mcp"])
@pytest.mark.parametrize("assistant", [None, "cursor"])
def test_codex_mode_requires_explicit_codex_selection(tmp_path, tool, assistant):
    args = eligible(tool)
    if assistant:
        args["context"].assistant = assistant
        catalog = args["catalog"]
        args["catalog"] = catalog.model_copy(
            update={
                "tools": tuple(
                    t.model_copy(update={"supported_assistants": [assistant]})
                    if t.tool_id == tool
                    else t
                    for t in catalog.tools
                )
            }
        )
    request = plan(tmp_path, tool).model_copy(update={"assistant": assistant})
    report = check_plan(request, **args)
    assert not report.is_ready_to_apply and "assistant" in report.checks[0].message


def test_plan_and_context_assistants_cannot_disagree(tmp_path):
    request = plan(tmp_path).model_copy(update={"assistant": "cursor"})
    report = check_plan(request, **eligible("headroom"))
    assert not report.is_ready_to_apply and "assistant" in report.checks[0].message


@pytest.mark.parametrize("tool", ["graphify", "playwright-mcp"])
def test_upstream_linux_support_is_not_local_mode_support(tmp_path, tool):
    args = eligible(tool)
    args["context"].platform = Platform.LINUX
    catalog = args["catalog"]
    args["catalog"] = catalog.model_copy(
        update={
            "tools": tuple(
                t.model_copy(update={"supported_platforms": [Platform.LINUX]})
                if t.tool_id == tool
                else t
                for t in catalog.tools
            )
        }
    )
    report = check_plan(plan(tmp_path, tool), **args)
    assert not report.is_ready_to_apply and "target" in report.checks[0].message

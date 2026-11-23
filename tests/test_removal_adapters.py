"""Adapter install/remove/reinstall contracts using declared command doubles."""

import pytest
from promptfoo_fakes import FakeCommands as PromptfooCommands
from test_graphify_install_adapter import FakeInstall, plan, project  # noqa: F401
from test_headroom_adapter import FakeCommands as HeadroomCommands
from test_playwright_adapter import Runner, client, runtime  # noqa: F401

from stackwinnow.adapters import (
    graphify_install,
    graphify_plan,
    headroom,
    playwright_mcp,
    promptfoo,
)
from stackwinnow.adapters.headroom_state import inspect_installation
from stackwinnow.removal import apply_removal, plan_removal_lifecycle


def remove(root, tool):
    result = apply_removal(plan_removal_lifecycle(root, [tool]))
    assert result.status == "succeeded", (root / result.journal).read_text()
    assert result.retired_tools == [tool]


def test_headroom_can_reinstall_without_losing_retained_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(headroom.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(headroom.platform, "machine", lambda: "arm64")
    first = headroom.apply_headroom(
        headroom.plan_headroom(tmp_path), command_runner=HeadroomCommands()
    )
    assert first.status == "succeeded"
    reports = list((tmp_path / ".stackwinnow/headroom/reports").glob("*.json"))
    before = {p: p.read_bytes() for p in reports}
    remove(tmp_path, "headroom")
    assert inspect_installation(tmp_path) is None
    result = headroom.apply_headroom(
        headroom.plan_headroom(tmp_path), command_runner=HeadroomCommands()
    )
    assert result.status == "succeeded", result.message
    assert all(p.read_bytes() == raw for p, raw in before.items())
    remove(tmp_path, "headroom")


def test_graphify_install_can_reinstall_with_fresh_recipe(project, plan):  # noqa: F811
    assert graphify_install.apply_graphify_install(plan, command_runner=FakeInstall()).installed
    remove(project, "graphify")
    fresh = graphify_plan.plan_graphify_execution(project, expectation=plan.expectation)
    result = graphify_install.apply_graphify_install(fresh, command_runner=FakeInstall())
    assert result.installed, result.results
    remove(project, "graphify")


def test_promptfoo_restored_file_and_reports_survive_reinstallation(tmp_path, monkeypatch):
    monkeypatch.setattr(promptfoo.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(promptfoo.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(promptfoo.shutil, "which", lambda name: "/declared/" + name)
    first = promptfoo.apply_promptfoo(
        promptfoo.plan_promptfoo(tmp_path), command_runner=PromptfooCommands()
    )
    assert first.status == "succeeded"
    report = tmp_path / first.evaluation.result_path
    before = report.read_bytes()
    remove(tmp_path, "promptfoo")
    second = promptfoo.apply_promptfoo(
        promptfoo.plan_promptfoo(tmp_path), command_runner=PromptfooCommands()
    )
    assert second.status == "succeeded", second.message
    assert report.read_bytes() == before
    remove(tmp_path, "promptfoo")


@pytest.mark.parametrize("user_changed", [False, True])
def test_promptfoo_partial_removal_preserves_restoration_proof(tmp_path, monkeypatch, user_changed):
    from stackwinnow import removal

    monkeypatch.setattr(promptfoo.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(promptfoo.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(promptfoo.shutil, "which", lambda name: "/declared/" + name)
    first = promptfoo.apply_promptfoo(
        promptfoo.plan_promptfoo(tmp_path), command_runner=PromptfooCommands()
    )
    assert first.status == "succeeded"
    real = removal._removal_fs.remove_tree

    def fail(*args):
        raise OSError("controlled deletion failure")

    monkeypatch.setattr(removal._removal_fs, "remove_tree", fail)
    result = apply_removal(plan_removal_lifecycle(tmp_path, ["promptfoo"]))
    assert result.status == "failed"
    if user_changed:
        (tmp_path / first.plan.configuration.relative_path).write_text('{"user": "preserve"}')
    monkeypatch.setattr(removal._removal_fs, "remove_tree", real)
    remove(tmp_path, "promptfoo")
    if user_changed:
        with pytest.raises(promptfoo.PromptfooError, match="without StackWinnow ownership"):
            promptfoo.plan_promptfoo(tmp_path)
        assert (
            tmp_path / first.plan.configuration.relative_path
        ).read_text() == '{"user": "preserve"}'
        return
    second = promptfoo.apply_promptfoo(
        promptfoo.plan_promptfoo(tmp_path), command_runner=PromptfooCommands()
    )
    assert second.status == "succeeded", second.message


def test_playwright_retained_output_survives_reinstallation(tmp_path, runtime, client):  # noqa: F811
    first = playwright_mcp.apply_playwright(
        playwright_mcp.plan_playwright(tmp_path, assistant="codex"), command_runner=Runner(tmp_path)
    )
    assert first.status == "succeeded", first.message
    output = tmp_path / playwright_mcp.STATE / "output/user.txt"
    output.write_text("keep user output")
    remove(tmp_path, "playwright-mcp")
    second = playwright_mcp.apply_playwright(
        playwright_mcp.plan_playwright(tmp_path, assistant="codex"), command_runner=Runner(tmp_path)
    )
    assert second.status == "succeeded", second.message
    assert output.read_text() == "keep user output"
    remove(tmp_path, "playwright-mcp")

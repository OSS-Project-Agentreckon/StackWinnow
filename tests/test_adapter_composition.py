"""A composition guard must reject concurrent changes under the shared lock."""

from contextlib import contextmanager

import pytest

from stackwinnow import installer
from stackwinnow.adapters import headroom, playwright_mcp, promptfoo
from stackwinnow.runner import CommandResult


@pytest.mark.parametrize("tool", ["headroom", "promptfoo", "playwright-mcp"])
def test_composition_guard_runs_under_shared_lock_before_receipts(tool, tmp_path, monkeypatch):
    monkeypatch.setattr(headroom.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(headroom.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(promptfoo.shutil, "which", lambda name: "/declared/" + name)
    locked = False
    original = installer.project_lock

    @contextmanager
    def lock(root):
        nonlocal locked
        with original(root):
            locked = True
            try:
                yield
            finally:
                locked = False

    monkeypatch.setattr(installer, "project_lock", lock)
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        assert args[-1] == "--version", "No install command may run after guard rejection"
        return CommandResult(0, "v24.13.1" if args[0].endswith("node") else "codex-cli 0.169.0", "")

    guarded = []

    def guard():
        assert locked
        assert not (tmp_path / ".stackwinnow/receipts.json").exists()
        guarded.append(True)
        raise installer.InstallerError("Concurrent workflow input change")

    plan, apply = {
        "headroom": (lambda: headroom.plan_headroom(tmp_path), headroom.apply_headroom),
        "promptfoo": (lambda: promptfoo.plan_promptfoo(tmp_path), promptfoo.apply_promptfoo),
        "playwright-mcp": (
            lambda: playwright_mcp.plan_playwright(tmp_path, assistant="codex"),
            playwright_mcp.apply_playwright,
        ),
    }[tool]
    result = apply(plan(), command_runner=runner, before_execute=guard)
    assert result.status == "blocked"
    assert guarded == [True]
    assert not (tmp_path / ".stackwinnow/receipts.json").exists()
    assert not (tmp_path / ".stackwinnow/envs").exists()

"""Actual installed-manager narrow lifecycles; no paid model provider."""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

import stackwinnow

pytestmark = pytest.mark.integration
EXPECTATION = {
    "caller_file": "sample_app/greetings.py",
    "caller_label": "greet()",
    "callee_file": "sample_app/names.py",
    "callee_label": "normalize_name()",
}
RUNTIMES = {
    "graphify": [".stackwinnow/envs/graphify"],
    "headroom": [".stackwinnow/envs/headroom/python"],
    "promptfoo": [".stackwinnow/envs/promptfoo/node"],
    "playwright-mcp": [
        ".stackwinnow/envs/playwright-mcp/node",
        ".stackwinnow/envs/playwright-mcp/browsers",
    ],
}


def assert_functional_report(report, tools, scenario):
    assert {tool["tool_id"] for tool in report["tools"]} == set(tools)
    evidence = set()
    for tool in report["tools"]:
        checks = {check["kind"]: check for check in tool["checks"]}
        assert checks["installed"]["status"] == checks["configured"]["status"] == "succeeded"
        expected_connection = (
            "succeeded" if tool["tool_id"] in {"graphify", "playwright-mcp"} else "not_applicable"
        )
        assert checks["connected"]["status"] == expected_connection
        assert checks["functional"]["status"] == ("succeeded" if scenario == "pass" else "failed")
        assert checks["functional"]["evidence"]
        evidence.update(item["source"] for item in checks["functional"]["evidence"])
        if expected_connection == "succeeded":
            path = Path(report["project_root"]) / checks["functional"]["evidence"][0]["source"]
            actual = json.loads(path.read_text())
            assert actual["provider"] == "scripted-loopback"
            assert [call["tool"] for call in actual["calls"]] == (
                ["query_relationship"]
                if tool["tool_id"] == "graphify"
                else ["browser_navigate", "browser_click", "browser_evaluate"]
            )
    return evidence


class Journey:
    def __init__(self, root: Path, output: Path, environment: dict[str, str]):
        self.root, self.output, self.environment = root, output, environment
        self.output.mkdir()
        self.calls: list[dict] = []
        self.fresh_evidence: set[str] = set()

    def call(self, *args, code=0):
        command = [sys.executable, "-I", "-B", "-m", "stackwinnow", *map(str, args)]
        started = time.monotonic()
        process = subprocess.run(
            command,
            cwd=self.output,
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=1200,
        )
        row = {
            "argv": command,
            "returncode": process.returncode,
            "elapsed_seconds": time.monotonic() - started,
            "stdout": process.stdout,
            "stderr": process.stderr,
        }
        self.calls.append(row)
        (self.output / "commands.json").write_text(json.dumps(self.calls, indent=2))
        assert process.returncode == code, row
        return json.loads(process.stdout) if process.stdout.strip() else None

    def plan(self, name, *args):
        result = self.call(*args, "--json")
        destination = self.output / (name + ".json")
        destination.write_text(json.dumps(result, indent=2))
        return destination

    def check(self, tools, *, fresh=False, scenario="pass", ready=False):
        args = ["check", str(self.root)]
        for tool in tools:
            args.extend(["--tool", tool])
        if fresh:
            args.append("--run-functional")
        report = self.call(*args, "--scenario", scenario, "--json", code=0 if ready else 1)
        assert report["ready"] is ready
        if fresh and (ready or scenario == "fail"):
            evidence = assert_functional_report(report, tools, scenario)
            assert evidence.isdisjoint(self.fresh_evidence)
            assert all((self.root / source).is_file() for source in evidence)
            self.fresh_evidence.update(evidence)
        return report

    def remove(self, tools, name, *, retired=True):
        args = ["remove", "plan", str(self.root)]
        for tool in tools:
            args.extend(["--tool", tool])
        plan = self.plan(name, *args)
        receipts = (self.root / ".stackwinnow/receipts.json").read_bytes()
        self.call("remove", "apply", plan, "--dry-run", "--json")
        assert (self.root / ".stackwinnow/receipts.json").read_bytes() == receipts
        result = self.call("remove", "apply", plan, "--json")
        assert set(result["retired_tools"]) == (set(tools) if retired else set())
        if retired:
            assert all(not (self.root / p).exists() for tool in tools for p in RUNTIMES[tool])
        return result

    def preserve_python_licenses(self, tool):
        interpreter = self.root / f".stackwinnow/envs/{tool}/python/bin/python"
        destination = self.output / (tool + "-artifacts")
        destination.mkdir(exist_ok=True)
        # Inspect the actual installed artifacts before removal, without importing
        # upstream code or writing into its immutable environment. Candidate texts
        # are evidence for later review, not an assertion of license closure.
        script = """
import hashlib, importlib.metadata, json, sys
from pathlib import Path
destination = Path(sys.argv[1])
rows = []
for dist in importlib.metadata.distributions():
    row = {"name": dist.metadata.get("Name"), "version": dist.version,
           "license": dist.metadata.get("License"),
           "license_expression": dist.metadata.get("License-Expression"), "files": []}
    for entry in dist.files or []:
        name = entry.name.lower()
        if not name.startswith(("license", "licence", "notice", "copying")) or name.endswith((".py", ".pyc")):
            continue
        path = Path(dist.locate_file(entry))
        if path.is_file() and not path.is_symlink() and path.stat().st_size <= 4 * 1024 * 1024:
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            (destination / digest).write_bytes(raw)
            row["files"].append({"path": str(entry), "sha256": digest})
    rows.append(row)
(destination / "index.json").write_text(json.dumps(rows, indent=2))
"""
        process = subprocess.run(
            [str(interpreter), "-I", "-B", "-c", script, str(destination)],
            cwd=self.output,
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert process.returncode == 0, process.stderr

    def preserve_node_lock(self, tool):
        lock = self.root / f".stackwinnow/envs/{tool}/node/node_modules/.package-lock.json"
        shutil.copyfile(lock, self.output / (tool + "-installed-lock.json"))


@pytest.fixture
def journey(fixture_project, tmp_path, subprocess_env):
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        pytest.skip("Real foundation acceptance targets macOS arm64.")
    source = Path(__file__).resolve().parents[2] / "src"
    assert not Path(stackwinnow.__file__).resolve().is_relative_to(source), (
        "Build and install the manager into an isolated environment before this acceptance."
    )
    return Journey(fixture_project.root.resolve(), tmp_path / "acceptance-evidence", subprocess_env)


def _user_snapshot(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _unchanged(root, before):
    assert all((root / path).read_bytes() == raw for path, raw in before.items())


def test_installed_cli_rejects_missing_prerequisites_and_damaged_receipts(journey):
    j, root = journey, journey.root
    before = _user_snapshot(root)
    j.environment = {**j.environment, "PATH": str(j.output / "no-executables")}
    plan = j.plan("missing-prerequisites", "playwright-mcp", "plan", root, "--assistant", "codex")
    blocked = j.call("playwright-mcp", "apply", plan, "--json", code=1)
    assert blocked["status"] == "blocked"
    assert "Node 24" in blocked["message"] and "Codex CLI 0.169.0" in blocked["message"]
    assert not (root / ".stackwinnow").exists()
    state = root / ".stackwinnow"
    state.mkdir()
    receipts = state / "receipts.json"
    receipts.write_text('{"interrupted-json":')
    j.call("remove", "plan", root, "--tool", "headroom", "--json", code=2)
    assert receipts.read_text() == '{"interrupted-json":'
    assert sorted(p.name for p in state.iterdir()) == ["receipts.json"]
    _unchanged(root, before)


@pytest.mark.parametrize("tool", ["headroom", "promptfoo"])
def test_real_library_cli_remove_and_reinstall(journey, tool):
    j, root = journey, journey.root
    before = _user_snapshot(root)
    j.check([tool], fresh=True)
    plan = j.plan("initial", tool, "plan", root)
    j.call(tool, "apply", plan, "--dry-run", "--json")
    assert not (root / ".stackwinnow").exists()
    first = j.call(tool, "apply", plan, "--json")
    assert first["status"] == "succeeded"
    j.check([tool])
    positive = j.check([tool], fresh=True, ready=True)
    j.check([tool], fresh=True, scenario="fail")
    repeat = j.plan("repeat", tool, "plan", root)
    repeated = j.call(tool, "apply", repeat, "--json")
    assert repeated["status"] == "succeeded"
    if tool == "headroom":
        assert first["compression"]["tokens_saved"] == 0
        j.preserve_python_licenses(tool)
        data = root / ".stackwinnow/headroom"
        retained = {
            p: hashlib.sha256(p.read_bytes()).hexdigest() for p in data.rglob("*") if p.is_file()
        }
    else:
        assert first["evaluation"]["successes"] == 2
        j.preserve_node_lock(tool)
        report = Path(first["evaluation"]["result_path"])
        report = report if report.is_absolute() else root / report
        retained = {report: hashlib.sha256(report.read_bytes()).hexdigest()}
        result = json.loads(report.read_text())
        assert result["results"]["stats"]["tokenUsage"]["total"] == 0
    assert positive["tools"][0]["checks"][2]["status"] == "not_applicable"
    j.remove([tool], "remove-first")
    absent = j.check([tool])
    assert absent["tools"][0]["checks"][0]["status"] != "succeeded"
    j.remove([tool], "remove-repeat", retired=False)
    assert all(
        hashlib.sha256(p.read_bytes()).hexdigest() == digest for p, digest in retained.items()
    )
    if tool == "headroom":
        retained = {
            p: digest
            for p, digest in retained.items()
            if p.is_relative_to(data / "reports") or p.is_relative_to(data / "cache/tiktoken")
        }
        assert retained
    reinstall = j.plan("reinstall", tool, "plan", root)
    assert j.call(tool, "apply", reinstall, "--json")["status"] == "succeeded"
    j.check([tool], fresh=True, ready=True)
    assert all(
        hashlib.sha256(p.read_bytes()).hexdigest() == digest for p, digest in retained.items()
    )
    j.remove([tool], "remove-final")
    _unchanged(root, before)


def test_real_shared_codex_cli_source_changes_removal_and_reinstall(journey):
    j, root = journey, journey.root
    if not platform.python_version().startswith("3.11."):
        pytest.skip("Graphify locked mode requires CPython3.11.")
    (root / ".codex").mkdir()
    config = root / ".codex/config.toml"
    original = '# user comment\n[mcp_servers.other]\ncommand = "/do-not-start"\n'
    config.write_text(original)
    before = _user_snapshot(root)
    expected = j.output / "expectation.json"
    expected.write_text(json.dumps(EXPECTATION))
    tools = ["graphify", "playwright-mcp"]

    def install(cycle):
        plan = j.plan(
            cycle + "-graphify-install",
            "graphify",
            "execution-plan",
            root,
            "--expectation",
            expected,
        )
        j.call("graphify", "apply", plan, "--install-only", "--dry-run", "--json")
        assert j.call("graphify", "apply", plan, "--install-only", "--json")["installed"]
        index = j.plan(cycle + "-index", "graphify", "index-plan", root, "--expectation", expected)
        assert j.call("graphify", "index", index, "--json")["indexed"]
        settings = j.plan(cycle + "-config", "graphify", "configure-plan", root)
        assert j.call("graphify", "configure", settings, "--json")["configured"]
        browser = j.plan(
            cycle + "-playwright", "playwright-mcp", "plan", root, "--assistant", "codex"
        )
        assert j.call("playwright-mcp", "apply", browser, "--json")["status"] == "succeeded"
        return plan, index

    execution, index = install("first")
    j.check(tools)
    j.check(tools, fresh=True, ready=True)
    j.check(tools, fresh=True, scenario="fail")
    assert j.call("graphify", "apply", execution, "--install-only", "--json")["installed"]
    browser = j.plan("playwright-repeat", "playwright-mcp", "plan", root, "--assistant", "codex")
    assert j.call("playwright-mcp", "apply", browser, "--json")["status"] == "succeeded"
    changed = root / "sample_app/names.py"
    changed.write_bytes(changed.read_bytes() + b"\n# Deliberate reviewed source revision.\n")
    before[changed.relative_to(root)] = changed.read_bytes()
    j.call("graphify", "index", index, "--json", code=2)
    fresh = j.plan("revised-index", "graphify", "index-plan", root, "--expectation", expected)
    assert j.call("graphify", "index", fresh, "--json")["indexed"]
    j.check(tools, fresh=True, ready=True)
    configured = config.read_text()
    marker = "[mcp_servers.stackwinnow_graphify]\n"
    assert marker in configured
    prefix, table = configured.split(marker, 1)
    lines = table.splitlines(keepends=True)
    command = next(i for i, line in enumerate(lines) if line.startswith('"command" = '))
    lines[command] = '"command" = "./user-wrapper"\n'
    config.write_text(prefix + marker + "".join(lines))
    preview = j.plan("modified-settings", "remove", "plan", root, "--tool", "graphify")
    assert json.loads(preview.read_text())["runtimes"][0]["action"] == "retain"
    j.call("remove", "apply", preview, "--json")
    assert "./user-wrapper" in config.read_text()
    config.write_text(configured)  # Explicit fixture user repair, never receipt editing.
    j.preserve_python_licenses("graphify")
    j.preserve_node_lock("playwright-mcp")
    graph_data = root / ".stackwinnow/graphify"
    retained = {
        p: hashlib.sha256(p.read_bytes()).hexdigest() for p in graph_data.rglob("*") if p.is_file()
    }
    j.remove(tools, "remove-both")
    assert config.read_text() == original
    assert all(
        hashlib.sha256(p.read_bytes()).hexdigest() == digest for p, digest in retained.items()
    )
    history = {
        p: digest
        for p, digest in retained.items()
        if p.relative_to(graph_data).parts[0].startswith("run-")
    }
    assert history
    j.remove(tools, "remove-both-repeat", retired=False)
    install("reinstall")
    j.check(tools, fresh=True, ready=True)
    assert all(
        hashlib.sha256(p.read_bytes()).hexdigest() == digest for p, digest in history.items()
    )
    j.remove(tools, "remove-both-final")
    assert config.read_text() == original
    _unchanged(root, before)

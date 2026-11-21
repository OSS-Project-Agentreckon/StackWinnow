"""Locked planning detects unsafe, changed, or forged inputs without effects."""

import errno
import os

import pytest
from pydantic import ValidationError

from stackwinnow.adapters import graphify_plan as adapter
from stackwinnow.adapters.graphify import GraphifyError, RelationshipExpectation
from stackwinnow.installer import ExecutionRecord, StepReceipt


@pytest.fixture
def expected():
    return RelationshipExpectation(
        caller_file="caller.py",
        caller_label="call()",
        callee_file="callee.py",
        callee_label="answer()",
    )


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project with spaces"
    root.mkdir()
    (root / "caller.py").write_text("from callee import answer\ndef call(): return answer()\n")
    (root / "callee.py").write_text("def answer(): return 42\n")
    return root


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("outcome", ["success", "fdopen-error", "directory", "oversized"])
def test_reader_closes_all_descriptors_on_success_and_failure(tmp_path, monkeypatch, outcome):
    parent = tmp_path / "nested"
    parent.mkdir()
    source = parent / "source.py"
    if outcome == "directory":
        source.mkdir()
    else:
        source.write_bytes(b"source")
    opened = []
    open_file = os.open

    def track_open(*args, **kwargs):
        descriptor = open_file(*args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def fail_fdopen(*args, **kwargs):
        raise OSError(errno.EIO, "simulated stream creation failure")

    monkeypatch.setattr(adapter.os, "open", track_open)
    if outcome == "fdopen-error":
        monkeypatch.setattr(adapter.os, "fdopen", fail_fdopen)
    try:
        if outcome == "success":
            assert adapter._read_at(tmp_path, "nested/source.py") == b"source"
        else:
            with pytest.raises((OSError, GraphifyError)):
                adapter._read_at(
                    tmp_path, "nested/source.py", limit=1 if outcome == "oversized" else 100
                )
        assert len(opened) == 3  # Root, nested directory, and file.
        for descriptor in opened:
            with pytest.raises(OSError) as error:
                os.fstat(descriptor)
            assert error.value.errno == errno.EBADF
    finally:
        # Keep the regression's failing baseline from leaking into later tests.
        for descriptor in opened:
            try:
                os.close(descriptor)
            except OSError:
                pass


def test_plan_roundtrip_revalidation_is_offline_and_read_only(
    project, expected, tmp_path, monkeypatch
):
    def forbidden(*args, **kwargs):
        raise AssertionError("Planning must not execute or access network")

    monkeypatch.setattr("subprocess.Popen", forbidden)
    monkeypatch.setattr("socket.socket", forbidden)
    before = snapshot(project)
    plan = adapter.plan_graphify_execution(project, expectation=expected)
    saved = tmp_path / "plan.json"
    saved.write_text(plan.model_dump_json())
    assert adapter.load_graphify_execution_plan(saved) == plan
    assert not plan.ready_to_apply and plan.blockers
    assert plan.phase == "execution-preparation" and plan.scope == "local-install-index"
    assert plan.network_required  # future acquisition; planning itself is offline
    assert {source.path for source in plan.sources} == {"caller.py", "callee.py"}
    assert before == snapshot(project)
    assert not (project / ".stackwinnow").exists()


def test_lock_covers_required_dependencies_and_emits_hashes():
    lock = adapter.load_graphify_lock()
    requirements = adapter.graphify_requirements().splitlines()
    assert len(requirements) == len(lock.packages)
    assert all(" --hash=sha256:" in line for line in requirements)
    assert {item.name for item in lock.packages} >= {
        "graphifyy",
        "numpy",
        "tree-sitter-python",
        "tree-sitter-groovy",
        "tree-sitter-json",
    }
    raw = lock.model_dump()
    raw["packages"] = tuple(item for item in raw["packages"] if item["name"] != "numpy")
    with pytest.raises(ValidationError, match="required dependency"):
        adapter.GraphifyLock.model_validate(raw)


@pytest.mark.parametrize("change", ["url", "version", "hash", "duplicate", "platform"])
def test_invalid_lock_metadata_is_rejected(change):
    raw = adapter.load_graphify_lock().model_dump(mode="json")
    if change == "duplicate":
        raw["packages"].append(raw["packages"][0])
    elif change == "platform":
        wheel = next(x for x in raw["packages"] if x["name"] == "numpy")
        wheel["url"] = wheel["url"].replace("macosx_14_0_arm64", "win_amd64")
    else:
        key, value = {
            "url": ("url", "https://example.org/evil.whl"),
            "version": ("version", "0.0.1"),
            "hash": ("sha256", "0" * 64),
        }[change]
        raw["packages"][0][key] = value
    with pytest.raises(ValidationError):
        adapter.GraphifyLock.model_validate(raw)


def test_changed_bundled_lock_is_rejected(monkeypatch, tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/graphify-lock.json").write_text("{}")
    monkeypatch.setattr(adapter, "files", lambda name: tmp_path)
    with pytest.raises(GraphifyError, match="dependency lock"):
        adapter.load_graphify_lock()


@pytest.mark.parametrize("change", ["source", "receipt", "runtime", "environment"])
def test_stale_plan_is_rejected(project, expected, monkeypatch, change):
    plan = adapter.plan_graphify_execution(project, expectation=expected)
    if change == "source":
        (project / "callee.py").write_text("def answer(): return 'changed'\n")
    elif change == "receipt":
        (project / ".stackwinnow").mkdir()
        (project / ".stackwinnow/receipts.json").write_text(
            ExecutionRecord(project_root=str(project)).model_dump_json()
        )
    elif change == "runtime":
        monkeypatch.setattr(
            adapter,
            "_runtime",
            lambda: plan.runtime.model_copy(update={"executable": "/different/python"}),
        )
    else:
        (project / adapter.ENV_PATH).mkdir(parents=True)
    with pytest.raises(GraphifyError):
        adapter.validate_graphify_execution_plan(plan)


@pytest.mark.parametrize(
    "field,value",
    [
        ("ready_to_apply", True),
        ("operations", ("run-arbitrary-command",)),
        ("graph_path", "/outside/graph.json"),
        ("lock_sha256", "0" * 64),
        ("blockers", ()),
        ("packages", ()),
        ("sources", ()),
    ],
)
def test_unchecked_model_updates_cannot_bypass_plan_validation(project, expected, field, value):
    plan = adapter.plan_graphify_execution(project, expectation=expected)
    with pytest.raises(GraphifyError):
        adapter.validate_graphify_execution_plan(plan.model_copy(update={field: value}))


def test_catalog_policy_is_rechecked(project, expected, monkeypatch):
    plan = adapter.plan_graphify_execution(project, expectation=expected)
    catalog = adapter.load_catalog()
    catalog.get("graphify").license_review = "unreviewed"
    monkeypatch.setattr(adapter, "load_catalog", lambda: catalog)
    with pytest.raises(GraphifyError, match="catalog"):
        adapter.validate_graphify_execution_plan(plan)


@pytest.mark.parametrize("kind", ["leaf-link", "parent-link", "fifo", "large", "missing"])
def test_unreadable_or_unsafe_source_is_rejected(project, expected, tmp_path, kind):
    source = project / "caller.py"
    source.unlink()
    if kind == "leaf-link":
        outside = tmp_path / "outside.py"
        outside.write_text("private content")
        source.symlink_to(outside)
    elif kind == "parent-link":
        (project / "linked").symlink_to(tmp_path, target_is_directory=True)
        expected = expected.model_copy(update={"caller_file": "linked/outside.py"})
        (tmp_path / "outside.py").write_text("private content")
    elif kind == "fifo":
        os.mkfifo(source)
    elif kind == "large":
        source.write_bytes(b"x" * (adapter.MAX_INPUT_BYTES + 1))
    with pytest.raises(GraphifyError) as error:
        adapter.plan_graphify_execution(project, expectation=expected)
    assert "private content" not in str(error.value)


@pytest.mark.parametrize("kind", ["duplicate", "wrong-root", "malformed", "owned"])
def test_invalid_or_existing_ownership_blocks_fresh_plan(project, expected, kind):
    receipt = StepReceipt(
        step_id="previous",
        tool_id="graphify" if kind == "owned" else "promptfoo",
        status="succeeded",
        message="previous operation",
        timestamp="2026-11-21T00:00:00Z",
    )
    record = ExecutionRecord(
        project_root="/another/project" if kind == "wrong-root" else str(project),
        steps=[receipt, receipt] if kind == "duplicate" else [receipt],
    )
    path = project / ".stackwinnow/receipts.json"
    path.parent.mkdir()
    path.write_text("private malformed state" if kind == "malformed" else record.model_dump_json())
    before = path.read_bytes()
    with pytest.raises(GraphifyError) as error:
        adapter.plan_graphify_execution(project, expectation=expected)
    assert "private malformed state" not in str(error.value)
    assert path.read_bytes() == before


def test_other_tools_and_dry_run_receipts_are_not_adopted(project, expected):
    record = ExecutionRecord(
        project_root=str(project),
        steps=[
            StepReceipt(
                step_id="preview",
                tool_id="graphify",
                status="skipped",
                message="dry run",
                timestamp="2026-11-21T00:00:00Z",
                dry_run=True,
            )
        ],
    )
    path = project / ".stackwinnow/receipts.json"
    path.parent.mkdir()
    path.write_text(record.model_dump_json())
    plan = adapter.plan_graphify_execution(project, expectation=expected)
    assert plan.receipts_sha256
    assert not plan.ready_to_apply
    assert adapter.validate_graphify_execution_plan(plan) == plan


def test_recursive_expectation_has_one_source_snapshot(project):
    expected = RelationshipExpectation(
        caller_file="caller.py",
        callee_file="caller.py",
        caller_label="call()",
        callee_label="call()",
    )
    assert len(adapter.plan_graphify_execution(project, expectation=expected).sources) == 1


def test_unsupported_host_is_explicit_without_preventing_preview(project, expected, monkeypatch):
    runtime = adapter._runtime().model_copy(update={"system": "Linux", "version": "3.14.0"})
    monkeypatch.setattr(adapter, "_runtime", lambda: runtime)
    plan = adapter.plan_graphify_execution(project, expectation=expected)
    assert any("macOS 14+" in blocker for blocker in plan.blockers)
    assert not plan.ready_to_apply


def test_missing_nofollow_support_returns_actionable_error(project, expected, monkeypatch):
    monkeypatch.delattr(adapter.os, "O_NOFOLLOW")
    with pytest.raises(GraphifyError, match="POSIX"):
        adapter.plan_graphify_execution(project, expectation=expected)


@pytest.mark.parametrize("kind", ["malformed", "duplicate", "symlink", "oversized", "traversal"])
def test_expectation_file_rejects_unsafe_inputs(tmp_path, expected, kind):
    path = tmp_path / "expected.json"
    if kind == "malformed":
        path.write_text("private malformed input")
    elif kind == "duplicate":
        path.write_text('{"caller_file":"a", "caller_file":"b"}')
    elif kind == "symlink":
        target = tmp_path / "target.json"
        target.write_text(expected.model_dump_json())
        path.symlink_to(target)
    elif kind == "oversized":
        path.write_text(" " * 65537)
    else:
        path.write_text(
            expected.model_copy(update={"caller_file": "../outside.py"}).model_dump_json()
        )
    with pytest.raises(GraphifyError, match="expectation JSON"):
        adapter.load_relationship_expectation(path)


def test_saved_plan_rejects_duplicate_keys(project, expected, tmp_path):
    plan = adapter.plan_graphify_execution(project, expectation=expected)
    path = tmp_path / "plan.json"
    path.write_text('{"scope":"other",' + plan.model_dump_json()[1:])
    with pytest.raises(GraphifyError):
        adapter.load_graphify_execution_plan(path)

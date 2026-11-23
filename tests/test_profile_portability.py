"""Portable intent is replanned through production workflows, never copied as state."""

import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_workflow import EXPECTATION, Commands, graph_report, request
from test_workflow import project as project

from stackwinnow import profiles, workflow
from stackwinnow.adapters import headroom
from stackwinnow.profiles import (
    PortableProfile,
    ProfileError,
    export_profile,
    import_profile,
    load_profile,
)
from stackwinnow.supported import supported_modes


def files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_export_replans_distinct_destination_without_local_state(project):
    (project / ".codex").mkdir()
    (project / ".codex/config.toml").write_text('private_value = "do-not-export-this-secret"\n')
    source = workflow.plan_workflow(project, request("headroom", "promptfoo"))
    source.request.goals = ("do-not-export-this-private-goal",)
    source.request.model_preference = "hosted"
    source.checksum = workflow._checksum(source)
    destination = project.parent / "destination"
    destination.mkdir()
    (destination / "package.json").write_text('{"name":"different-project"}')
    before = files(destination)
    profile = export_profile(source)
    encoded = profile.model_dump_json()
    for excluded in (
        str(project),
        source.workflow_id,
        "private-goal",
        "secret",
        "state",
        "checksum",
        "goals",
    ):
        assert excluded not in encoded
    assert profile.model_preference == "hosted"
    assert profile.requirements == {
        m.tool_id: m.requirements
        for m in supported_modes()
        if m.tool_id in ("headroom", "promptfoo")
    }
    first = import_profile(profile, destination)
    second = import_profile(profile, destination)
    assert first.project_root == str(destination)
    assert first.workflow_id != source.workflow_id and first.workflow_id != second.workflow_id
    assert first.request.goals == () and first.request.tool_ids == source.request.tool_ids
    assert not first.state.record.steps and not first.graphify_reuse
    assert first.state.inputs != source.state.inputs
    commands = Commands(destination)
    assert workflow.apply_workflow(first, dry_run=True, command_runner=commands).dry_run
    assert not commands.calls and files(destination) == before
    assert not (destination / ".stackwinnow").exists()


def test_profile_from_used_plan_can_be_explicitly_applied_elsewhere(project):
    source = workflow.plan_workflow(project, request("headroom"))
    assert workflow.apply_workflow(source, command_runner=Commands(project)).ready
    # Export only reads the saved document: the source can have changed or moved.
    project.rename(project.with_name("moved-source"))
    profile = export_profile(source)
    destination = project.parent / "fresh-destination"
    destination.mkdir()
    fresh = import_profile(profile, destination)
    assert not fresh.state.record.steps
    assert not (destination / ".stackwinnow").exists()
    result = workflow.apply_workflow(fresh, command_runner=Commands(destination))
    assert result.ready and result.verification.run_functional
    assert result.project_root == str(destination)
    before = files(destination)
    repeated = import_profile(profile, destination)
    assert repeated.state.record.steps and repeated.workflow_id != fresh.workflow_id
    assert all(
        (destination / p).is_relative_to(destination)
        for s in repeated.state.record.steps
        for p in s.owned_paths
    )
    assert str(project) not in repeated.model_dump_json()
    assert files(destination) == before


def test_graphify_profile_preserves_relative_relationship_and_new_sources(project):
    source = workflow.plan_workflow(project, request("graphify", expectation=EXPECTATION))
    profile = export_profile(source)
    destination = project.parent / "graph-destination"
    shutil.copytree(project, destination)
    (destination / "callee.py").write_text("def answer(): return 43\n")
    before = files(destination)
    fresh = import_profile(profile, destination)
    assert fresh.request.expectation == EXPECTATION
    assert fresh.graphify.project_root == str(destination)
    assert fresh.state.sources != source.state.sources
    assert not fresh.state.record.steps and not fresh.graphify_reuse
    assert str(project) not in fresh.model_dump_json()
    assert files(destination) == before and not (destination / ".stackwinnow").exists()


def test_graphify_import_reuses_only_destinations_original_runtime(project, monkeypatch):
    source = workflow.plan_workflow(project, request("graphify", expectation=EXPECTATION))
    profile = export_profile(source)
    destination = project.parent / "existing-graph-destination"
    shutil.copytree(project, destination)
    monkeypatch.setattr(workflow, "check_project", graph_report)
    original = workflow.plan_workflow(destination, request("graphify", expectation=EXPECTATION))
    assert workflow.apply_workflow(original, command_runner=Commands(destination)).ready
    before = files(destination)
    imported = import_profile(profile, destination)
    assert imported.graphify_reuse and imported.graphify == original.graphify
    assert imported.graphify != source.graphify
    assert imported.state.record.steps and files(destination) == before


@pytest.mark.parametrize("version", [None, True, 1.0, "1", 0, 2])
def test_schema_is_required_exact_integer_version(project, version):
    data = export_profile(workflow.plan_workflow(project, request("headroom"))).model_dump()
    if version is None:
        data.pop("schema_version")
    else:
        data["schema_version"] = version
    with pytest.raises(ValidationError):
        PortableProfile.model_validate(data)


@pytest.mark.parametrize(
    "change",
    ["unknown", "mode", "version", "duplicate", "assistant", "requirements", "missing-expectation"],
)
def test_unsupported_or_inconsistent_profile_rejected(project, change):
    data = export_profile(workflow.plan_workflow(project, request("headroom"))).model_dump(
        mode="json"
    )
    if change == "unknown":
        data["selections"][0]["tool_id"] = "aider"
    elif change in ("mode", "version"):
        data["selections"][0][change] = "unsupported"
    elif change == "duplicate":
        data["selections"].append(data["selections"][0])
    elif change == "assistant":
        data["assistant"] = "cursor"
    elif change == "requirements":
        data["requirements"]["headroom"] = ["any platform"]
    else:
        data["selections"] = [
            profiles.ToolSelection(tool_id="graphify", mode="codex", version="0.9.114").model_dump()
        ]
    with pytest.raises(ValidationError):
        PortableProfile.model_validate(data)


@pytest.mark.parametrize("location", ["selection", "expectation"])
def test_nested_extra_fields_rejected(project, location):
    data = export_profile(
        workflow.plan_workflow(project, request("graphify", expectation=EXPECTATION))
    ).model_dump(mode="json")
    nested = data["selections"][0] if location == "selection" else data["expectation"]
    nested["credential"] = "private"
    with pytest.raises(ValidationError):
        PortableProfile.model_validate(data)


@pytest.mark.parametrize(
    "path",
    [
        "/Users/private/file.py",
        "C:/Users/private/file.py",
        "C:file.py",
        "../file.py",
        "a/../file.py",
        "./file.py",
        "a\\file.py",
        "~/.ssh/key",
        ".stackwinnow/private.py",
        ".STACKWINNOW/private.py",
        ".SSH/key.py",
        ".Aws/config.py",
        ".venv/module.py",
        "node_modules/package/index.js",
        ".env",
        ".ENV",
        "a/.Env.local",
        "a/.env.local",
        "a/line\n.py",
    ],
)
def test_private_and_nonportable_relationship_paths_rejected(project, path):
    data = export_profile(
        workflow.plan_workflow(project, request("graphify", expectation=EXPECTATION))
    ).model_dump(mode="json")
    data["expectation"]["caller_file"] = path
    with pytest.raises(ValidationError):
        PortableProfile.model_validate(data)


@pytest.mark.parametrize(
    "label", ["/Users/private/function", "C:\\secret", "name\nsecret", "Bearer private-token"]
)
def test_labels_cannot_smuggle_paths_or_freeform_text(project, label):
    data = export_profile(
        workflow.plan_workflow(project, request("graphify", expectation=EXPECTATION))
    ).model_dump(mode="json")
    data["expectation"]["caller_label"] = label
    with pytest.raises(ValidationError):
        PortableProfile.model_validate(data)


@pytest.mark.parametrize("change", ["platform", "architecture", "python", "macos"])
def test_incompatible_destination_host_rejected_without_writes(project, monkeypatch, change):
    profile = export_profile(
        workflow.plan_workflow(project, request("graphify", expectation=EXPECTATION))
    )
    if change == "platform":
        monkeypatch.setattr(headroom.platform, "system", lambda: "Linux")
    elif change == "architecture":
        monkeypatch.setattr(headroom.platform, "machine", lambda: "x86_64")
    elif change == "python":
        monkeypatch.setattr(headroom.platform, "python_version", lambda: "3.14.0")
    else:
        monkeypatch.setattr(headroom.platform, "mac_ver", lambda: ("13.0", (), "arm64"))
    with pytest.raises(ProfileError, match="require"):
        import_profile(profile, project)
    assert not (project / ".stackwinnow").exists()


def test_conflicts_checked_against_current_catalog(project, monkeypatch):
    profile = export_profile(workflow.plan_workflow(project, request("headroom", "promptfoo")))
    catalog = profiles.load_catalog()
    catalog.get("headroom").conflicts.append("promptfoo")
    monkeypatch.setattr(profiles, "load_catalog", lambda: catalog)
    with pytest.raises(ProfileError, match="Invalid"):
        import_profile(profile, project)


def test_tampered_workflow_document_cannot_be_exported(project):
    plan = workflow.plan_workflow(project, request("headroom"))
    plan.request.model_preference = "hosted"
    with pytest.raises(ProfileError):
        export_profile(plan)


@pytest.mark.parametrize(
    "raw", ['{"schema_version":1,"schema_version":1}', "[]", '{"schema_version":NaN}']
)
def test_invalid_or_duplicate_profile_json_rejected(tmp_path, raw):
    path = tmp_path / "profile.json"
    path.write_text(raw)
    with pytest.raises(ProfileError):
        load_profile(path)


@pytest.mark.parametrize(
    "name,tool_id",
    [
        ("local-compression", "headroom"),
        ("local-evaluation", "promptfoo"),
        ("browser-codex", "playwright-mcp"),
        ("code-map-codex", "graphify"),
    ],
)
def test_documented_profiles_produce_pure_workflow_previews(
    project, fixture_project, name, tool_id
):
    profile = load_profile(Path(__file__).parents[1] / "examples/profiles" / (name + ".json"))
    root = fixture_project.root
    before = files(root)
    planned = import_profile(profile, root)
    assert planned.request.tool_ids == [tool_id]
    assert workflow.apply_workflow(planned, dry_run=True).dry_run
    assert files(root) == before and not (root / ".stackwinnow").exists()

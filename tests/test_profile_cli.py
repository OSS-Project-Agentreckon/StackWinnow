"""Public profile CLI output, input diagnostics and explicit destination review."""

import json

import pytest
from test_workflow import project as project
from test_workflow import request

from stackwinnow import workflow
from stackwinnow.cli import main
from stackwinnow.profiles import export_profile


@pytest.mark.parametrize(
    "field", ["environment", "project_root", "api_key", "state", "ready", "commands", "goals"]
)
def test_unknown_sensitive_fields_not_reflected_by_cli(project, tmp_path, capsys, field):
    data = export_profile(workflow.plan_workflow(project, request("headroom"))).model_dump(
        mode="json"
    )
    data[field] = "secret-do-not-print"
    saved = tmp_path / "bad-profile.json"
    saved.write_text(json.dumps(data))
    with pytest.raises(SystemExit) as error:
        main(["profile", "import", str(saved), str(project), "--json"])
    assert error.value.code == 2
    output = capsys.readouterr()
    assert not output.out and "secret-do-not-print" not in output.err
    assert not (project / ".stackwinnow").exists()


def test_cli_export_import_json_and_human_preview(project, tmp_path, capsys):
    plan = workflow.plan_workflow(project, request("headroom"))
    saved = tmp_path / "source-plan.json"
    saved.write_text(plan.model_dump_json())
    assert main(["profile", "export", str(saved), "--json"]) == 0
    profile_path = tmp_path / "portable.json"
    profile_path.write_text(capsys.readouterr().out)
    destination = tmp_path / "destination"
    destination.mkdir()
    assert main(["profile", "import", str(profile_path), str(destination), "--json"]) == 0
    imported = workflow.WorkflowPlan.model_validate_json(capsys.readouterr().out)
    assert imported.project_root == str(destination) and not imported.state.record.steps
    reviewed = tmp_path / "destination-plan.json"
    reviewed.write_text(imported.model_dump_json())
    assert main(["workflow", "apply", str(reviewed), "--dry-run", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"]
    assert main(["profile", "import", str(profile_path), str(destination)]) == 0
    assert "No installation or verification ran" in capsys.readouterr().out
    assert not (destination / ".stackwinnow").exists()

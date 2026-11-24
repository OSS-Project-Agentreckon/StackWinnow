"""Workbench API parity and review gates; no real installation or provider calls."""

from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from ui import api


@pytest.fixture
def client():
    api._plans.clear()
    with TestClient(api.app, base_url="http://localhost") as client:
        yield client
    api._plans.clear()


@pytest.fixture
def project(tmp_path):
    (tmp_path / "app.py").write_text(
        "from openai import OpenAI\nclient=OpenAI()\n"
        'client.responses.create(model="private-literal", input="hello")\n'
    )
    (tmp_path / "data.csv").write_text("private-data\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "vendor.js").write_text("private-vendor")
    return str(tmp_path)


def test_live_contract_reports_real_source_inventory_without_goals(client, project):
    response = client.post("/api/recommend", json={"project_root": project})
    assert response.status_code == 200
    result = response.json()
    source = result["inspection"]["source_discovery"]
    assert source["files_scanned"] == 1
    assert source["model_calls"] == 1
    assert source["languages"] == {"Python": 1}
    assert {f["path"]: f["status"] for f in source["files"]} == {
        "app.py": "scanned",
        "data.csv": "unsupported",
        "node_modules": "excluded",
    }
    assert any(r["kind"] == "source" for t in result["recommendations"] for r in t["reasons"])
    assert "private-literal" not in response.text
    assert "private-data" not in response.text


def test_assistant_changes_compatibility_not_source_evidence(client, project):
    codex = client.post(
        "/api/recommend", json={"project_root": project, "assistant": "codex"}
    ).json()
    aider = client.post(
        "/api/recommend", json={"project_root": project, "assistant": "aider"}
    ).json()
    assert codex["inspection"]["source_discovery"] == aider["inspection"]["source_discovery"]
    codex_tool = client.get("/api/catalog/graphify?assistant=codex").json()
    aider_tool = client.get("/api/catalog/graphify?assistant=aider").json()
    assert codex_tool["eligibility"] != aider_tool["eligibility"]
    assert (
        client.post(
            "/api/recommend", json={"project_root": project, "assistant": "openai"}
        ).status_code
        == 422
    )
    meta = client.get("/api/meta").json()
    assert meta["api_revision"] == 2
    assert "codex" in meta["assistants"] and "openai" not in meta["assistants"]
    assert "reports" in meta["features"] and not meta["provider_calls"]


def test_reviewed_plan_export_and_import(client, project, tmp_path):
    response = client.post(
        "/api/workflow/plan", json={"project_root": project, "tool_ids": ["headroom"]}
    )
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["phases"] == ["headroom", "verify"]
    assert plan["document"]["request"]["selections"][0]["tool_id"] == "headroom"
    exported = client.post("/api/profiles/export", json={"plan_id": plan["plan_id"]})
    assert exported.status_code == 200, exported.text
    assert exported.json()["kind"] == "stackwinnow-profile"
    destination = tmp_path / "destination"
    destination.mkdir()
    imported = client.post(
        "/api/profiles/import", json={"project_root": str(destination), "profile": exported.json()}
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["document"]["project_root"] == str(destination)
    assert not (tmp_path / ".stackwinnow").exists()


def test_apply_requires_local_token_confirmation_and_unmodified_server_plan(
    client, project, monkeypatch
):
    plan = client.post(
        "/api/workflow/plan", json={"project_root": project, "tool_ids": ["headroom"]}
    ).json()
    calls = []

    def apply(document, dry_run=False):
        calls.append((document, dry_run))
        return SimpleNamespace(as_payload=lambda: {"status": "skipped" if dry_run else "succeeded"})

    monkeypatch.setattr(api, "apply_workflow", apply)
    body = {"plan_id": plan["plan_id"], "confirm": True}
    assert client.post("/api/workflow/apply", json=body).status_code == 403
    headers = {"X-StackWinnow-Token": client.get("/api/meta").json()["action_token"]}
    assert (
        client.post(
            "/api/workflow/apply", json={"plan_id": plan["plan_id"]}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/workflow/apply",
            json={**body, "document": {"command": "untrusted"}},
            headers=headers,
        ).status_code
        == 422
    )
    assert not calls
    assert (
        client.post(
            "/api/workflow/apply",
            json={"plan_id": plan["plan_id"], "dry_run": True},
            headers=headers,
        ).status_code
        == 200
    )
    assert client.post("/api/workflow/apply", json=body, headers=headers).status_code == 200
    assert calls[0][1] is True and calls[1][1] is False
    assert calls[1][0].checksum == plan["document"]["checksum"]
    assert client.post("/api/workflow/apply", json=body, headers=headers).status_code == 409
    assert len(calls) == 2


def test_origin_expiry_and_invalid_selections_are_actionable(client, project):
    assert (
        client.get("/api/meta", headers={"Origin": "https://untrusted.example"}).status_code == 403
    )
    assert client.get("/api/meta", headers={"Host": "untrusted.example"}).status_code == 403
    assert (
        client.post(
            "/api/workflow/plan", json={"project_root": project, "tool_ids": ["litellm"]}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/workflow/plan", json={"project_root": project, "tool_ids": ["graphify"]}
        ).status_code
        == 422
    )
    assert client.get("/api/catalog?category=invalid").status_code == 422
    assert client.get("/api/catalog/not-a-tool").status_code == 404
    plan = client.post(
        "/api/workflow/plan", json={"project_root": project, "tool_ids": ["headroom"]}
    ).json()
    api._plans[plan["plan_id"]]["created"] -= 3601
    assert client.post("/api/profiles/export", json={"plan_id": plan["plan_id"]}).status_code == 409


def test_report_respects_scan_scope_and_status_is_passive(client, project):
    report = client.post("/api/reports", json={"project_root": project, "scan_source": False})
    assert report.status_code == 200, report.text
    assert (
        report.json()["json"]["recommendation"]["inspection"]["source_discovery"]["status"]
        == "not-scanned"
    )
    scanned = client.post("/api/reports", json={"project_root": project}).json()
    assert "app.py:3" in scanned["markdown"]
    status = client.post(
        "/api/workflow/status", json={"project_root": project, "tool_ids": ["headroom"]}
    )
    assert status.status_code == 200, status.text
    assert status.json()["run_functional"] is False
    assert status.json()["ready"] is False


def test_graphify_relationship_is_forwarded_and_paths_validated(client, project, monkeypatch):
    requests = []

    def plan(root, request):
        requests.append(request)
        return SimpleNamespace(
            phases=["graphify-index", "verify"],
            model_dump=lambda **kw: request.model_dump(mode="json"),
        )

    monkeypatch.setattr(api, "plan_workflow", plan)
    expectation = {
        "caller_file": "app.py",
        "caller_label": "answer",
        "callee_file": "app.py",
        "callee_label": "helper",
    }
    body = {"project_root": project, "tool_ids": ["graphify"], "expectation": expectation}
    response = client.post("/api/workflow/plan", json=body)
    assert response.status_code == 200, response.text
    assert requests[0].expectation.model_dump() == expectation
    assert (
        client.post(
            "/api/workflow/plan",
            json={**body, "expectation": {**expectation, "caller_file": "../outside.py"}},
        ).status_code
        == 422
    )
    assert len(requests) == 1


def test_removal_and_functional_checks_require_explicit_review(client, project, monkeypatch):
    calls = []
    monkeypatch.setattr(
        api,
        "plan_removal_lifecycle",
        lambda root, ids: SimpleNamespace(
            model_dump=lambda **kw: {"project_root": str(root), "tool_ids": ids}
        ),
    )
    monkeypatch.setattr(
        api,
        "apply_removal",
        lambda plan, dry_run=False: (
            calls.append("removal")
            or SimpleNamespace(model_dump=lambda **kw: {"status": "succeeded"})
        ),
    )
    monkeypatch.setattr(
        api,
        "check_project",
        lambda *args, **kwargs: (
            calls.append("check") or SimpleNamespace(as_payload=lambda: {"ready": True})
        ),
    )
    planned = client.post(
        "/api/removal/plan", json={"project_root": project, "tool_ids": ["headroom"]}
    ).json()
    headers = {"X-StackWinnow-Token": client.get("/api/meta").json()["action_token"]}
    assert (
        client.post(
            "/api/removal/apply", json={"plan_id": planned["plan_id"]}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/workflow/check",
            json={"project_root": project, "tool_ids": ["headroom"]},
            headers=headers,
        ).status_code
        == 422
    )
    assert not calls
    assert (
        client.post(
            "/api/removal/apply",
            json={"plan_id": planned["plan_id"], "confirm": True},
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/workflow/check",
            json={"project_root": project, "tool_ids": ["headroom"], "confirm": True},
            headers=headers,
        ).status_code
        == 200
    )
    assert calls == ["removal", "check"]

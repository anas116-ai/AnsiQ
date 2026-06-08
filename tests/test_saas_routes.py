"""Integration tests for SaaS routes: crews and tasks."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

import saas.app as saas_app
from saas.models import UserRole


async def _fake_user_owner():
    return SimpleNamespace(id="test-user", role=UserRole.OWNER, organization_id="test-org")


def test_crews_crud_and_execute(monkeypatch):
    # Override auth dependency so FastAPI uses our fake owner user
    import saas.auth as saas_auth

    saas_app.app.dependency_overrides[saas_auth.get_current_user] = _fake_user_owner
    client = TestClient(saas_app.app)

    payload = {
        "name": "research_crew",
        "agents": [{"role": "Researcher", "goal": "Find info"}],
        "tasks": [{"description": "Research {topic}", "expected_output": "Summary"}],
        "process": "pipeline",
    }

    r = client.post("/api/v1/crews", json=payload)
    print('DEBUG /crews response', r.status_code, r.text)
    assert r.status_code == 201
    data = r.json()
    crew_id = data["id"]

    r = client.get("/api/v1/crews")
    assert r.status_code == 200
    assert r.json()["total"] >= 1

    r = client.get(f"/api/v1/crews/{crew_id}")
    assert r.status_code == 200

    # Execute
    exec_r = client.post(f"/api/v1/crews/{crew_id}/execute", json={"inputs": {"topic": "AI"}})
    assert exec_r.status_code == 200
    exec_data = exec_r.json()
    assert "tasks_output" in exec_data

    # Delete
    del_r = client.delete(f"/api/v1/crews/{crew_id}")
    assert del_r.status_code == 204


def test_tasks_crud_and_execute(monkeypatch):
    import saas.auth as saas_auth

    saas_app.app.dependency_overrides[saas_auth.get_current_user] = _fake_user_owner
    client = TestClient(saas_app.app)

    payload = {"name": "research_task", "description": "Research {topic}", "expected_output": "Summary"}
    r = client.post("/api/v1/tasks", json=payload)
    print('DEBUG /tasks response', r.status_code, r.text)
    assert r.status_code == 201
    tid = r.json()["id"]

    r = client.get("/api/v1/tasks")
    assert r.status_code == 200
    assert r.json()["total"] >= 1

    r = client.post(f"/api/v1/tasks/{tid}/execute", json={})
    assert r.status_code == 200
    out = r.json()
    assert out.get("status") == "completed"

    del_r = client.delete(f"/api/v1/tasks/{tid}")
    assert del_r.status_code == 204

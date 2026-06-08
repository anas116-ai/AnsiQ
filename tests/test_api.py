"""Tests for the REST API server.

Tests all endpoints using FastAPI's TestClient:
- Health check
- Agent CRUD and chat
- Crew creation and execution
- Memory browsing
- Knowledge sources and query
- Skills management
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ansiq.api.server import create_app
from ansiq.api.state import reset_app_state


@pytest.fixture(autouse=True)
def reset_state(mock_factory, tmp_path):
    """Reset app state with temp DB, initialize memory and RAG stores."""
    # Use a temp DB path for test isolation (each test gets its own DB)
    db_path = str(tmp_path / "api_state.db")
    reset_app_state(db_path=db_path)
    from ansiq.api.state import get_app_state
    from ansiq.knowledge.engine import RAGEngine
    from ansiq.knowledge.store import VectorKnowledgeStore
    from ansiq.memory.fts_store import FTSMemoryStore
    state = get_app_state()
    state.memory_store = FTSMemoryStore()
    state.rag_engine = RAGEngine(
        store=VectorKnowledgeStore(store_path=tmp_path / "knowledge.json")
    )
    yield
    # Cleanup: close persistence connection and reset API key cache
    state.persistence.close()
    from ansiq.api.auth import reload_api_keys
    reload_api_keys()


@pytest.fixture
def client():
    """Create test client with fresh app."""
    app = create_app()
    return TestClient(app)


class TestHealth:
    """Test /api/health endpoint."""

    def test_health(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_root(self, client):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "docs" in data


class TestAgents:
    """Test /api/agents endpoints."""

    def test_list_agents_empty(self, client):
        response = client.get("/api/agents")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["agents"] == []

    def test_create_agent(self, client):
        response = client.post("/api/agents", json={
            "role": "Researcher",
            "goal": "Find information",
            "backstory": "An expert researcher.",
            "llm_provider": "openai",
            "llm_model": "gpt-4o",
        })
        assert response.status_code == 201
        data = response.json()
        assert data["role"] == "Researcher"
        assert data["id"] == "researcher"
        assert data["tools_count"] == 0

    def test_create_and_list(self, client):
        # Create
        client.post("/api/agents", json={
            "role": "Analyst",
            "goal": "Analyze data",
        })
        # List
        response = client.get("/api/agents")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["agents"][0]["role"] == "Analyst"

    def test_get_agent(self, client):
        # Create first
        client.post("/api/agents", json={
            "role": "Writer",
            "goal": "Write content",
        })
        # Get
        response = client.get("/api/agents/writer")
        assert response.status_code == 200
        assert response.json()["role"] == "Writer"

    def test_get_agent_not_found(self, client):
        response = client.get("/api/agents/nonexistent")
        assert response.status_code == 404

    def test_delete_agent(self, client):
        # Create then delete
        client.post("/api/agents", json={"role": "TempAgent", "goal": "Temp"})
        response = client.delete("/api/agents/tempagent")
        assert response.status_code == 204
        # Verify deleted
        response = client.get("/api/agents/tempagent")
        assert response.status_code == 404

    def test_delete_agent_not_found(self, client):
        response = client.delete("/api/agents/nonexistent")
        assert response.status_code == 404

    def test_persist_agent_across_restart(self, client, tmp_path):
        """Create an agent, reset state, verify it's still there (persistence)."""
        client.post("/api/agents", json={
            "role": "PersistentAgent",
            "goal": "Survive restarts",
            "llm_provider": "mock",
        })
        # Simulate restart by resetting app state with same DB
        from ansiq.api.state import get_app_state, reset_app_state
        reset_app_state(db_path=str(tmp_path / "api_state.db"))
        state = get_app_state()
        assert "persistentagent" in state.agents
        assert state.agents["persistentagent"].identity.role == "PersistentAgent"

    def test_chat_with_agent(self, client):
        # Create agent with mock provider
        client.post("/api/agents", json={
            "role": "Assistant",
            "goal": "Help users",
            "llm_provider": "mock",
            "llm_model": "mock-model",
        })
        # Chat
        response = client.post("/api/agents/assistant/chat", json={
            "message": "Hello!",
        })
        assert response.status_code == 200
        data = response.json()
        assert "content" in data

    def test_chat_agent_not_found(self, client):
        response = client.post("/api/agents/nonexistent/chat", json={
            "message": "Hi",
        })
        assert response.status_code == 404

    def test_run_agent_task(self, client):
        # Create agent with mock provider
        client.post("/api/agents", json={
            "role": "Worker",
            "goal": "Execute tasks",
            "llm_provider": "mock",
            "llm_model": "mock-model",
        })
        # Run task
        response = client.post("/api/agents/worker/run", json={
            "task": "Do something",
        })
        assert response.status_code == 200
        data = response.json()
        assert "content" in data

    def test_stream_endpoint(self, client):
        """Test SSE streaming returns event stream."""
        client.post("/api/agents", json={
            "role": "Streamer",
            "goal": "Stream responses",
            "llm_provider": "mock",
            "llm_model": "mock-model",
        })
        response = client.post("/api/agents/streamer/stream", json={
            "message": "Stream test",
        })
        assert response.status_code == 200
        # SSE response should have text/event-stream content type
        assert "text/event-stream" in response.headers.get("content-type", "")


class TestCrews:
    """Test /api/crews endpoints."""

    def test_list_crews_empty(self, client):
        response = client.get("/api/crews")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0

    def test_create_crew(self, client):
        response = client.post("/api/crews", json={
            "name": "Research Crew",
            "agents": [
                {"role": "Researcher", "goal": "Research topics"},
                {"role": "Writer", "goal": "Write reports"},
            ],
            "tasks": [
                {"description": "Research AI", "expected_output": "Findings", "agent_role": "Researcher"},
                {"description": "Write summary", "expected_output": "Report", "agent_role": "Writer"},
            ],
            "process": "pipeline",
        })
        assert response.status_code == 201
        data = response.json()
        assert data["agents_count"] == 2
        assert data["tasks_count"] == 2
        assert data["id"] == "research_crew"

    def test_get_crew(self, client):
        client.post("/api/crews", json={
            "name": "Test Crew",
            "agents": [{"role": "Agent1", "goal": "Test"}],
            "tasks": [{"description": "Test task", "expected_output": "Done"}],
        })
        response = client.get("/api/crews/test_crew")
        assert response.status_code == 200
        assert response.json()["agents_count"] == 1

    def test_get_crew_not_found(self, client):
        response = client.get("/api/crews/nonexistent")
        assert response.status_code == 404

    def test_delete_crew(self, client):
        client.post("/api/crews", json={
            "name": "Temp Crew",
            "agents": [{"role": "Worker", "goal": "Work"}],
            "tasks": [{"description": "Do task", "expected_output": "Done"}],
        })
        response = client.delete("/api/crews/temp_crew")
        assert response.status_code == 204
        # Verify deleted
        response = client.get("/api/crews/temp_crew")
        assert response.status_code == 404

    def test_delete_crew_not_found(self, client):
        response = client.delete("/api/crews/nonexistent")
        assert response.status_code == 404

    def test_persist_crew_across_restart(self, client, tmp_path):
        """Create a crew, reset state, verify it persists."""
        client.post("/api/crews", json={
            "name": "Persistent Crew",
            "agents": [{"role": "Researcher", "goal": "Research"}],
            "tasks": [{"description": "Research AI", "expected_output": "Findings"}],
        })
        # Simulate restart
        from ansiq.api.state import get_app_state, reset_app_state
        reset_app_state(db_path=str(tmp_path / "api_state.db"))
        state = get_app_state()
        assert "persistent_crew" in state.crews
        assert len(state.crews["persistent_crew"].agents) == 1

    def test_run_crew(self, client):
        client.post("/api/crews", json={
            "name": "Worker Crew",
            "agents": [{
                "role": "Worker",
                "goal": "Work",
                "llm_provider": "mock",
                "llm_model": "mock-model",
            }],
            "tasks": [{"description": "Execute task", "expected_output": "Done"}],
        })
        response = client.post("/api/crews/worker_crew/run", json={
            "inputs": {"topic": "AI"},
        })
        assert response.status_code == 200
        data = response.json()
        assert "tasks_output" in data


class TestMemory:
    """Test /api/memory endpoints."""

    def test_list_memory(self, client):
        response = client.get("/api/memory")
        assert response.status_code == 200
        data = response.json()
        assert "memories" in data

    def test_search_memory(self, client):
        response = client.post("/api/memory/search", json={
            "query": "test",
        })
        assert response.status_code == 200
        data = response.json()
        assert "memories" in data

    def test_memory_stats(self, client):
        response = client.get("/api/memory/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_memories" in data


class TestKnowledge:
    """Test /api/knowledge endpoints."""

    def test_query_empty(self, client):
        """Query without any sources returns empty results."""
        response = client.post("/api/knowledge/query", json={
            "query": "test",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0

    def test_add_text_source(self, client):
        response = client.post("/api/knowledge/sources", json={
            "name": "test_doc",
            "source_type": "text",
            "content": "This is test knowledge content for the RAG system.",
        })
        assert response.status_code == 201
        data = response.json()
        assert data["added"] is True

    def test_stats(self, client):
        response = client.get("/api/knowledge/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_chunks" in data


class TestSkills:
    """Test /api/skills endpoints."""

    def test_list_skills(self, client):
        response = client.get("/api/skills")
        assert response.status_code == 200
        data = response.json()
        assert "skills" in data

    def test_create_skill(self, client):
        response = client.post("/api/skills", json={
            "name": "test_skill",
            "description": "A test skill",
            "category": "testing",
        })
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "test_skill"


class TestErrors:
    """Test error handling."""

    def test_404_json(self, client):
        response = client.get("/api/agents/nonexistent")
        assert response.status_code == 404
        assert "detail" in response.json()

    def test_invalid_json(self, client):
        response = client.post("/api/agents", json={})
        assert response.status_code == 422  # Validation error

    def test_missing_required_field(self, client):
        response = client.post("/api/agents", json={"role": "Test"})
        assert response.status_code == 422  # Missing 'goal'


class TestWebSocket:
    """Test WebSocket endpoint."""

    def test_ws_agent_not_found(self, client):
        with client.websocket_connect("/ws/agents/nonexistent") as ws:
            ws.send_json({"message": "Hello"})
            response = ws.receive_json()
            # Should close with error
            assert response["type"] == "error"
            assert "not found" in response["content"]

    def test_ws_chat_with_agent(self, client):
        # Create an agent first
        client.post("/api/agents", json={
            "role": "WSChat",
            "goal": "WebSocket chat test",
            "llm_provider": "mock",
            "llm_model": "mock-model",
        })
        with client.websocket_connect("/ws/agents/wschat") as ws:
            ws.send_json({"message": "Hello via WS"})
            # Should receive tokens then done
            tokens = []
            while True:
                msg = ws.receive_json()
                if msg["type"] == "done":
                    break
                if msg["type"] == "error":
                    pytest.fail(f"WS error: {msg['content']}")
                tokens.append(msg["content"])
            assert len(tokens) > 0
            assert "mock" in "".join(tokens).lower()

    def test_ws_invalid_json(self, client):
        client.post("/api/agents", json={
            "role": "WSValidator",
            "goal": "Validate WS",
            "llm_provider": "mock",
        })
        with client.websocket_connect("/ws/agents/wsvalidator") as ws:
            ws.send_text("not-json")
            response = ws.receive_json()
            assert response["type"] == "error"

    def test_ws_empty_message(self, client):
        client.post("/api/agents", json={
            "role": "WSEmpty",
            "goal": "Empty msg test",
            "llm_provider": "mock",
        })
        with client.websocket_connect("/ws/agents/wsempty") as ws:
            ws.send_json({"message": ""})
            response = ws.receive_json()
            assert response["type"] == "error"
            assert "required" in response["content"]


class TestExportImport:
    """Test export/import endpoints."""

    def _setup_test_data(self, client):
        """Create a test agent and crew for export tests."""
        client.post("/api/agents", json={
            "role": "ExportAgent",
            "goal": "Test export",
            "llm_provider": "mock",
        })
        client.post("/api/crews", json={
            "name": "Export Crew",
            "agents": [{"role": "Worker", "goal": "Work"}],
            "tasks": [{"description": "Do task", "expected_output": "Done"}],
        })

    def test_export_agents(self, client):
        self._setup_test_data(client)
        response = client.get("/api/export/agents")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert any(a["identity"]["role"] == "ExportAgent" for a in data)

    def test_export_crews(self, client):
        self._setup_test_data(client)
        response = client.get("/api/export/crews")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert any(c["id"] == "export_crew" for c in data)

    def test_export_all(self, client):
        self._setup_test_data(client)
        response = client.get("/api/export/all")
        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert "agents" in data
        assert "crews" in data
        assert "knowledge" in data

    def test_import_agents(self, client):
        payload = [{
            "id": "imported_agent",
            "identity": {
                "role": "ImportedAgent",
                "goal": "Test import",
                "backstory": "I was imported",
            },
            "config": {
                "llm_provider": "mock",
                "llm_model": "mock-model",
                "temperature": 0.5,
            },
        }]
        response = client.post("/api/import/agents", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["imported"] == 1

        # Verify agent was created
        response = client.get("/api/agents/imported_agent")
        assert response.status_code == 200
        assert response.json()["role"] == "ImportedAgent"

    def test_import_crews(self, client):
        # First import the agent it references
        client.post("/api/import/agents", json=[{
            "id": "crew_worker",
            "identity": {"role": "CrewWorker", "goal": "Work in crew"},
            "config": {"llm_provider": "mock"},
        }])

        payload = [{
            "id": "imported_crew",
            "agents": [{"role": "CrewWorker", "goal": "Work in crew"}],
            "tasks": [{"description": "Crew task", "expected_output": "Done", "agent_role": "CrewWorker"}],
            "process": "pipeline",
        }]
        response = client.post("/api/import/crews", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["imported"] == 1

        # Verify crew was created
        response = client.get("/api/crews/imported_crew")
        assert response.status_code == 200

    def test_import_all(self, client):
        payload = {
            "version": "1.0",
            "agents": [{
                "id": "full_import_agent",
                "identity": {"role": "FullImport", "goal": "Full import test"},
                "config": {"llm_provider": "mock"},
            }],
            "crews": [{
                "id": "full_import_crew",
                "agents": [{"role": "FullImport", "goal": "Full import test"}],
                "tasks": [{"description": "Full import task", "expected_output": "Done"}],
                "process": "pipeline",
            }],
        }
        response = client.post("/api/import/all", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["imported"]["agents"]["imported"] == 1
        assert data["imported"]["crews"]["imported"] == 1

    def test_export_knowledge(self, client):
        response = client.get("/api/export/knowledge")
        assert response.status_code == 200
        data = response.json()
        assert "sources" in data


class TestAuth:
    """Test API key authentication."""

    def test_auth_disabled_by_default(self, client):
        """Without ANSIQ_API_KEYS, all requests should work."""
        from ansiq.api.auth import is_auth_enabled
        assert not is_auth_enabled()
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_auth_enabled_rejects_anonymous(self, monkeypatch):
        """With ANSIQ_API_KEYS set, requests without key should fail."""
        monkeypatch.setenv("ANSIQ_API_KEYS", "sk-test-123")
        from ansiq.api.auth import is_auth_enabled, reload_api_keys
        reload_api_keys()
        assert is_auth_enabled()

        from fastapi.testclient import TestClient

        from ansiq.api.server import create_app
        app = create_app()
        authed_client = TestClient(app)

        response = authed_client.get("/api/health")
        assert response.status_code == 401

    def test_auth_enabled_allows_valid_key(self, monkeypatch):
        """Valid Bearer token should pass."""
        monkeypatch.setenv("ANSIQ_API_KEYS", "sk-test-123")
        from ansiq.api.auth import reload_api_keys
        reload_api_keys()

        from fastapi.testclient import TestClient

        from ansiq.api.server import create_app
        app = create_app()
        authed_client = TestClient(app)

        response = authed_client.get(
            "/api/health",
            headers={"Authorization": "Bearer sk-test-123"},
        )
        assert response.status_code == 200

    def test_auth_allows_x_api_key_header(self, monkeypatch):
        """X-API-Key header should work."""
        monkeypatch.setenv("ANSIQ_API_KEYS", "sk-test-456")
        from ansiq.api.auth import reload_api_keys
        reload_api_keys()

        from fastapi.testclient import TestClient

        from ansiq.api.server import create_app
        app = create_app()
        authed_client = TestClient(app)

        response = authed_client.get(
            "/api/health",
            headers={"X-API-Key": "sk-test-456"},
        )
        assert response.status_code == 200


class TestTemplates:
    """Test agent template endpoints."""

    def test_list_templates(self, client):
        response = client.get("/api/templates")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 8  # All built-in templates
        assert any(t["id"] == "researcher" for t in data)
        assert any(t["id"] == "coder" for t in data)

    def test_list_templates_by_category(self, client):
        response = client.get("/api/templates?category=coding")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 2  # coder + developer
        assert all(t["category"] == "coding" for t in data)

    def test_get_template(self, client):
        response = client.get("/api/templates/researcher")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "researcher"
        assert "Senior Research Analyst" in data["role"]
        assert data["category"] == "analysis"

    def test_get_template_not_found(self, client):
        response = client.get("/api/templates/nonexistent")
        assert response.status_code == 404

    def test_create_agent_from_template(self, client):
        response = client.post("/api/templates/researcher/create")
        assert response.status_code == 201
        data = response.json()
        assert data["role"] == "Senior Research Analyst"
        assert data["id"] == "senior_research_analyst"

    def test_create_agent_from_template_with_overrides(self, client):
        response = client.post(
            "/api/templates/coder/create",
            params={"override_role": "Python Expert", "override_model": "claude-3-5-sonnet"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["role"] == "Python Expert"
        assert data["llm_model"] == "claude-3-5-sonnet"

    def test_create_agent_from_template_not_found(self, client):
        response = client.post("/api/templates/nonexistent/create")
        assert response.status_code == 404


class TestRateLimit:
    """Test rate limiting middleware."""

    def test_rate_limit_headers_present(self, client):
        response = client.get("/api/agents")
        assert response.status_code == 200
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers

    def test_health_endpoint_excluded(self, client):
        """Health endpoint should not have rate limit headers."""
        response = client.get("/api/health")
        assert response.status_code == 200
        # Health is excluded, so headers should not be set
        assert "X-RateLimit-Limit" not in response.headers

    def test_rate_limit_remaining_decreases(self, client):
        r1 = client.get("/api/agents")
        remaining1 = int(r1.headers["X-RateLimit-Remaining"])

        r2 = client.get("/api/agents")
        remaining2 = int(r2.headers["X-RateLimit-Remaining"])

        # Remaining should decrease by at least 1
        assert remaining2 <= remaining1

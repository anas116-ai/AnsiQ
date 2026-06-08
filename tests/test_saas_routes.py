"""Integration tests for SaaS routes: crews and tasks.

Uses an in-memory SQLite database and mocked LLM providers so the tests
run without external services (PostgreSQL, LLM APIs).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import saas.app as saas_app
import saas.auth as saas_auth
from saas.database import Base, get_db
from saas.models import UserRole


# ── In-memory SQLite test database ─────────────────────────────────────

_TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
_test_engine = create_async_engine(_TEST_DATABASE_URL, echo=False)
_TestSessionLocal = async_sessionmaker(
    bind=_test_engine, class_=AsyncSession, expire_on_commit=False
)


async def _override_get_db():
    """Provide an async database session backed by in-memory SQLite."""
    async with _TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Fake auth user ─────────────────────────────────────────────────────


async def _fake_user_owner():
    """Return a fake user object that satisfies route permission checks."""
    return SimpleNamespace(
        id="test-user",
        role=UserRole.OWNER,
        organization_id="test-org",
    )


# ── Mock LLM provider ──────────────────────────────────────────────────


class _MockLLMResponse:
    """Minimal LLM response that quacks like ``LLMResponse``."""

    def __init__(self, content: str = "Mock LLM response"):
        self.content = content
        self.model = "mock-model"
        self.finish_reason = "stop"
        self.usage = SimpleNamespace(
            prompt_tokens=10, completion_tokens=5, total_tokens=15
        )


class _MockProvider:
    """Stub LLM provider that never makes real API calls."""

    async def chat(self, messages, **kwargs):
        return _MockLLMResponse()

    async def stream_chat(self, messages, **kwargs):
        yield "Mock response"


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(scope="module", autouse=True)
def _create_test_tables():
    """Create all ORM tables once for the test module."""

    async def _setup():
        async with _test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_setup())
    finally:
        loop.close()
    yield


@pytest.fixture(autouse=True)
def _setup_dependency_overrides():
    """Override auth and DB dependencies for every test, then clean up."""
    saas_app.app.dependency_overrides[saas_auth.get_current_user] = _fake_user_owner
    saas_app.app.dependency_overrides[get_db] = _override_get_db
    yield
    saas_app.app.dependency_overrides.clear()


# ── Tests ──────────────────────────────────────────────────────────────


def test_crews_crud_and_execute():
    client = TestClient(saas_app.app)

    payload = {
        "name": "research_crew",
        "agents": [{"role": "Researcher", "goal": "Find info"}],
        "tasks": [{"description": "Research {topic}", "expected_output": "Summary"}],
        "process": "pipeline",
    }

    # CREATE
    r = client.post("/api/v1/crews", json=payload)
    assert r.status_code == 201, f"Create crew failed: {r.status_code} {r.text}"
    data = r.json()
    crew_id = data["id"]

    # LIST
    r = client.get("/api/v1/crews")
    assert r.status_code == 200
    assert r.json()["total"] >= 1

    # GET
    r = client.get(f"/api/v1/crews/{crew_id}")
    assert r.status_code == 200

    # EXECUTE — mock LLM provider to avoid real API calls
    mock_provider = _MockProvider()
    with patch("ansiq.core.agent.ProviderFactory.create", return_value=mock_provider):
        exec_r = client.post(
            f"/api/v1/crews/{crew_id}/execute",
            json={"inputs": {"topic": "AI"}},
        )
    assert exec_r.status_code == 200, f"Execute crew failed: {exec_r.status_code} {exec_r.text}"
    exec_data = exec_r.json()
    assert "tasks_output" in exec_data

    # DELETE
    del_r = client.delete(f"/api/v1/crews/{crew_id}")
    assert del_r.status_code == 204


def test_tasks_crud_and_execute():
    client = TestClient(saas_app.app)

    payload = {
        "name": "research_task",
        "description": "Research {topic}",
        "expected_output": "Summary",
    }
    r = client.post("/api/v1/tasks", json=payload)
    assert r.status_code == 201, f"Create task failed: {r.status_code} {r.text}"
    tid = r.json()["id"]

    # LIST
    r = client.get("/api/v1/tasks")
    assert r.status_code == 200
    assert r.json()["total"] >= 1

    # EXECUTE — mock LLM provider to avoid real API calls
    mock_provider = _MockProvider()
    with patch("ansiq.core.agent.ProviderFactory.create", return_value=mock_provider):
        exec_r = client.post(f"/api/v1/tasks/{tid}/execute", json={})
    assert exec_r.status_code == 200, f"Execute task failed: {exec_r.status_code} {exec_r.text}"
    out = exec_r.json()
    assert out.get("status") == "completed"

    # DELETE
    del_r = client.delete(f"/api/v1/tasks/{tid}")
    assert del_r.status_code == 204
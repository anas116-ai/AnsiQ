"""Integration tests for SaaS routes: crews and tasks.

Uses an in-memory SQLite database and mocked LLM providers so the tests
run without external services (PostgreSQL, LLM APIs).

Key design decisions:
  - Module-scoped engine + tables (created once, used by all tests).
  - Function-scoped DB session isolation (each test gets a clean session).
  - Proper async fixtures (no manual asyncio.new_event_loop()).
  - Engine is disposed after the module finishes.
  - Fake user is a full-featured mock that won't break if routes access
    additional User attributes.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)

import ansiq.llm.openai_provider  # noqa: F401
import ansiq.llm.ollama_provider  # noqa: F401

import saas.app as saas_app
import saas.auth as saas_auth
from saas.database import Base, get_db
from saas.models import UserRole


_TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
_test_engine = create_async_engine(_TEST_DATABASE_URL, echo=False)
_TestSessionLocal = async_sessionmaker(
    bind=_test_engine, class_=AsyncSession, expire_on_commit=False
)


async def _override_get_db() -> AsyncGenerator[AsyncSession]:
    async with _TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# --- Fake auth user ---------------------------------------------------------


def _make_fake_user(**overrides):
    base = {
        "id": "test-user",
        "email": "test@ansiq.ai",
        "full_name": "Test User",
        "role": UserRole.OWNER,
        "organization_id": "test-org",
        "is_active": True,
        "is_verified": True,
        "last_login_at": None,
        "preferences": {},
        "mfa_enabled": False,
        "deleted_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


_fake_user_owner = _make_fake_user()


# --- Mock LLM provider ------------------------------------------------------


class _MockLLMResponse:
    def __init__(self, content: str = "Mock LLM response"):
        self.content = content
        self.model = "mock-model"
        self.finish_reason = "stop"
        self.usage = SimpleNamespace(
            prompt_tokens=10, completion_tokens=5, total_tokens=15
        )


class _MockProvider:
    async def chat(self, messages, **kwargs):
        return _MockLLMResponse()

    async def stream_chat(self, messages, **kwargs):
        yield "Mock response"


# --- Fixtures -----------------------------------------------------------------


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _create_test_tables() -> AsyncGenerator[None]:
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _test_engine.dispose()


@pytest.fixture(autouse=True)
def _setup_dependency_overrides():
    saas_app.app.dependency_overrides[saas_auth.get_current_user] = (
        lambda: _fake_user_owner
    )
    saas_app.app.dependency_overrides[get_db] = _override_get_db
    yield
    saas_app.app.dependency_overrides.clear()


# --- Tests -------------------------------------------------------------------


def test_crews_crud_and_execute() -> None:
    client = TestClient(saas_app.app)
    payload = {
        "name": "research_crew",
        "agents": [{"role": "Researcher", "goal": "Find info"}],
        "tasks": [
            {"description": "Research {topic}", "expected_output": "Summary"}
        ],
        "process": "pipeline",
    }
    r = client.post("/api/v1/crews", json=payload)
    assert r.status_code == 201, f"Create crew failed: {r.status_code} {r.text}"
    data = r.json()
    crew_id = data["id"]
    assert data["name"] == "research_crew"
    assert data["agents_count"] == 1
    assert data["tasks_count"] == 1
    assert data["process"] == "pipeline"
    assert data["is_active"] is True
    r = client.get("/api/v1/crews")
    assert r.status_code == 200
    list_data = r.json()
    assert list_data["total"] >= 1
    assert any(c["id"] == crew_id for c in list_data["crews"])
    r = client.get(f"/api/v1/crews/{crew_id}")
    assert r.status_code == 200
    assert r.json()["id"] == crew_id
    mock_provider = _MockProvider()
    with patch(
        "ansiq.core.agent.ProviderFactory.create", return_value=mock_provider
    ):
        exec_r = client.post(
            f"/api/v1/crews/{crew_id}/execute",
            json={"inputs": {"topic": "AI"}},
        )
    assert (exec_r.status_code == 200),         f"Execute crew failed: {exec_r.status_code} {exec_r.text}"
    exec_data = exec_r.json()
    assert "tasks_output" in exec_data
    assert "raw_output" in exec_data
    del_r = client.delete(f"/api/v1/crews/{crew_id}")
    assert del_r.status_code == 204


def test_tasks_crud_and_execute() -> None:
    client = TestClient(saas_app.app)
    payload = {
        "name": "research_task",
        "description": "Research {topic}",
        "expected_output": "Summary",
    }
    r = client.post("/api/v1/tasks", json=payload)
    assert r.status_code == 201, f"Create task failed: {r.status_code} {r.text}"
    tid = r.json()["id"]
    assert r.json()["name"] == "research_task"
    r = client.get("/api/v1/tasks")
    assert r.status_code == 200
    list_data = r.json()
    assert list_data["total"] >= 1
    assert any(t["id"] == tid for t in list_data["tasks"])
    mock_provider = _MockProvider()
    with patch(
        "ansiq.core.agent.ProviderFactory.create", return_value=mock_provider
    ):
        exec_r = client.post(f"/api/v1/tasks/{tid}/execute", json={})
    assert (exec_r.status_code == 200),         f"Execute task failed: {exec_r.status_code} {exec_r.text}"
    out = exec_r.json()
    assert out.get("status") == "completed"
    assert "output" in out
    del_r = client.delete(f"/api/v1/tasks/{tid}")
    assert del_r.status_code == 204

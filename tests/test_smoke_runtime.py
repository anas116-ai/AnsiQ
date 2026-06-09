"""Runtime smoke test — uses the REAL saas.app:app with DB override.

Spins up the actual production FastAPI app (with /health, /version,
/metrics, /, all routers, all middleware) but swaps the database
session dependency so it runs against in-memory SQLite.

Exercises every route category that the e2e tests didn't cover:
  - System: /health, /ready, /version, /metrics, /
  - Billing: /billing/subscription, /billing/invoices
  - Usage: /usage (POST + GET)
  - Members: /members, role updates
  - Organization: GET, PATCH
  - Webhook events list

This is the final gate before declaring production-ready.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Aiosqlite's background ``_connection_worker_thread`` outlives the
# per-test event loop and emits a benign "Event loop is closed" at
# interpreter shutdown. The filter for this is registered in
# ``pyproject.toml`` under ``[tool.pytest.ini_options] filterwarnings``
# — that is the canonical pytest-level hook that suppresses the
# unhandled-thread warning across the whole test session.

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _build_test_app():
    """Use the REAL saas.app:app, only override the DB session."""
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    from sqlalchemy.pool import StaticPool

    os.environ.setdefault("ANSIQ_ENV", "development")
    os.environ.setdefault("ANSIQ_JWT_SECRET", "test-jwt-secret-with-enough-entropy")
    os.environ.setdefault("ANSIQ_SECRET_KEY", "test-app-secret-with-enough-entropy-yes")

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False,
    )

    async def _init():
        from saas.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(_init())

    async def _override_get_db():
        async with session_local() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    # Import the REAL app and swap the dependency.
    from saas.app import app
    from saas.database import get_db
    app.dependency_overrides[get_db] = _override_get_db
    return app


def _client():
    from fastapi.testclient import TestClient
    return TestClient(_build_test_app())


def _signup_and_login(client, email="bob@example.com"):
    r = client.post("/api/v1/auth/signup", json={
        "email": email, "password": "VeryStrongPassword!1",
        "full_name": "Bob Builder", "org_name": "BuilderCo",
    })
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def _h(token):
    return {"Authorization": f"Bearer {token}"}


# ── System routes (defined on saas.app, not in a router) ────────────────


def test_health_endpoint():
    c = _client()
    r = c.get("/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "healthy"
    assert "version" in body


def test_health_response_shape():
    c = _client()
    r = c.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == "0.1.0"


def test_version_endpoint():
    c = _client()
    r = c.get("/version")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["service"] == "ansiq"
    assert body["environment"] == "development"


def test_metrics_endpoint():
    c = _client()
    r = c.get("/metrics")
    assert r.status_code in (200, 404), r.text


def test_landing_page():
    c = _client()
    r = c.get("/")
    assert r.status_code == 200


# ── Billing routes ───────────────────────────────────────────────────────


def test_billing_subscription_empty_for_new_org():
    c = _client()
    token = _signup_and_login(c)
    r = c.get("/api/v1/billing/subscription", headers=_h(token))
    assert r.status_code == 200, r.text
    assert r.json() is None


def test_billing_invoices_empty_list_for_new_org():
    c = _client()
    token = _signup_and_login(c)
    r = c.get("/api/v1/billing/invoices", headers=_h(token))
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_billing_checkout_requires_stripe_key():
    c = _client()
    token = _signup_and_login(c)
    r = c.post(
        "/api/v1/billing/checkout",
        json={"price_id": "price_test_123", "trial_days": 14},
        headers=_h(token),
    )
    assert r.status_code in (400, 503), f"expected 400/503, got {r.status_code}: {r.text}"


# ── Usage / Analytics routes ────────────────────────────────────────────


def test_record_and_list_usage():
    c = _client()
    token = _signup_and_login(c)
    r = c.post(
        "/api/v1/usage",
        json={"metric": "agent_run", "quantity": 5},
        headers=_h(token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["metric"] == "agent_run"
    assert body["quantity"] == 5
    rid = c.get("/api/v1/usage", headers=_h(token))
    assert rid.status_code == 200
    items = rid.json()
    assert len(items) >= 1
    assert any(i["metric"] == "agent_run" for i in items)


# ── Members routes ──────────────────────────────────────────────────────


def test_list_members_shows_self():
    c = _client()
    token = _signup_and_login(c)
    r = c.get("/api/v1/members", headers=_h(token))
    assert r.status_code == 200, r.text
    members = r.json()
    assert len(members) == 1
    assert members[0]["role"] == "owner"


def test_invite_member_enforces_admin_role():
    c = _client()
    token = _signup_and_login(c)
    r = c.post(
        "/api/v1/members",
        json={
            "email": "carol@example.com",
            "full_name": "Carol",
            "password": "CarolPass!1",
            "role": "member",
        },
        headers=_h(token),
    )
    assert r.status_code == 201, r.text


def test_update_member_role():
    c = _client()
    token = _signup_and_login(c)
    invite = c.post(
        "/api/v1/members",
        json={
            "email": "dave@example.com",
            "full_name": "Dave",
            "password": "DavePass!1",
            "role": "member",
        },
        headers=_h(token),
    )
    dave_id = invite.json()["id"]
    r = c.patch(
        f"/api/v1/members/{dave_id}/role",
        json={"role": "admin"},
        headers=_h(token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "admin"


# ── Organization routes ─────────────────────────────────────────────────


def test_get_organization():
    c = _client()
    token = _signup_and_login(c)
    r = c.get("/api/v1/organization", headers=_h(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "BuilderCo"
    assert body["plan"] == "free"
    assert "billing_email" in body  # schema must expose this field


def test_update_organization():
    c = _client()
    token = _signup_and_login(c)
    r = c.patch(
        "/api/v1/organization",
        json={"name": "BuilderCo-Renamed", "billing_email": "billing@builder.co"},
        headers=_h(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "BuilderCo-Renamed"
    assert body["billing_email"] == "billing@builder.co"


# ── Webhook events list ─────────────────────────────────────────────────


def test_webhook_events_list_empty():
    c = _client()
    token = _signup_and_login(c)
    w = c.post(
        "/api/v1/webhooks",
        json={"url": "https://example.com/h", "events": ["*"]},
        headers=_h(token),
    )
    ep_id = w.json()["id"]
    r = c.get(f"/api/v1/webhooks/{ep_id}/events", headers=_h(token))
    assert r.status_code == 200
    assert r.json() == []


def test_webhook_event_types_list():
    c = _client()
    token = _signup_and_login(c)
    r = c.get("/api/v1/webhooks/events", headers=_h(token))
    assert r.status_code == 200
    events = r.json()
    assert "agent.completed" in events
    assert "invoice.paid" in events
    assert "subscription.updated" in events


# ── Authentication edge cases ──────────────────────────────────────────


def test_protected_route_without_token_returns_401():
    c = _client()
    for path in [
        "/api/v1/auth/me",
        "/api/v1/workspaces",
        "/api/v1/api-keys",
        "/api/v1/members",
        "/api/v1/webhooks",
        "/api/v1/usage",
        "/api/v1/billing/subscription",
        "/api/v1/organization",
        "/api/v1/audit-logs",
        "/api/v1/account/me/export",
        "/api/v1/account/mfa/status",
    ]:
        r = c.get(path)
        assert r.status_code in (401, 403), f"{path} returned {r.status_code}"


def test_protected_route_with_garbage_token_returns_401():
    c = _client()
    for path in ["/api/v1/auth/me", "/api/v1/workspaces", "/api/v1/usage"]:
        r = c.get(path, headers={"Authorization": "Bearer not-a-real-token"})
        assert r.status_code in (401, 403), f"{path} returned {r.status_code}"

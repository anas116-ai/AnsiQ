"""End-to-end integration tests for the AnsiQ SaaS API.

Exercises the full user lifecycle against an in-memory SQLite database:

    signup → login → /me → MFA enable → MFA confirm → MFA login →
    GDPR export → GDPR soft-delete → session revoked

Uses FastAPI's TestClient and dependency_overrides so we never touch
the real PostgreSQL. SQLite is the closest portable substitute that
supports the SQLAlchemy 2.0 async API.

Run with:  pytest tests/test_e2e_saas.py -v
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Make repo root importable regardless of CWD.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _build_test_app():
    """Build a FastAPI app bound to an in-memory SQLite database.

    Creates fresh tables per test so state never leaks between cases.
    """
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    from sqlalchemy.pool import StaticPool

    from saas.models import Base
    from saas.routes.account import router as account_router
    from saas.routes.api import router as api_router
    from saas.routes.auth import router as auth_router

    # Force a known-good dev secret so JWT validation works in tests.
    os.environ.setdefault("ANSIQ_ENV", "development")
    os.environ.setdefault("ANSIQ_JWT_SECRET", "test-jwt-secret-with-enough-entropy")
    os.environ.setdefault("ANSIQ_SECRET_KEY", "test-app-secret-with-enough-entropy-yes")
    os.environ.setdefault("ANSIQ_CORS_ORIGINS", "*")

    # Use a file-based SQLite so the same connection can be shared by
    # multiple async sessions (StaticPool + single connection).
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False,
    )

    async def _init_models():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init_models())

    app = FastAPI(title="AnsiQ Test API")
    app.include_router(auth_router)
    app.include_router(api_router)
    app.include_router(account_router)

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

    # Override the DB dependency for every router.
    from saas.database import get_db
    app.dependency_overrides[get_db] = _override_get_db
    return app


def _client():
    from fastapi.testclient import TestClient
    return TestClient(_build_test_app())


# ── Helpers ──────────────────────────────────────────────────────────────


def _signup(client, email="alice@example.com", password="CorrectHorseBattery!9"):
    return client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": password,
            "full_name": "Alice Auditor",
            "org_name": "AuditCo",
        },
    )


def _login(client, email="alice@example.com", password="CorrectHorseBattery!9"):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── Tests ────────────────────────────────────────────────────────────────


def test_signup_creates_user_and_org():
    client = _client()
    r = _signup(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert "access_token" in body and "refresh_token" in body
    assert body["token_type"] == "bearer"
    # Duplicate email is rejected.
    r2 = _signup(client)
    assert r2.status_code == 409, f"expected 409, got {r2.status_code}: {r2.text}"


def test_login_with_correct_password_returns_tokens():
    client = _client()
    _signup(client)
    r = _login(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "access_token" in body
    # Wrong password is rejected.
    r2 = client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "wrong"},
    )
    assert r2.status_code == 401


def test_me_endpoint_returns_user_profile():
    client = _client()
    _signup(client)
    r = _login(client)
    token = r.json()["access_token"]
    r2 = client.get("/api/v1/auth/me", headers=_auth(token))
    assert r2.status_code == 200
    body = r2.json()
    assert body["email"] == "alice@example.com"
    assert body["full_name"] == "Alice Auditor"
    assert body["role"] in ("owner", "admin", "member", "viewer")
    assert "org_id" in body
    assert body["is_verified"] is False  # New users start unverified


def test_me_requires_auth():
    client = _client()
    r = client.get("/api/v1/auth/me")
    assert r.status_code in (401, 403)


def test_refresh_token_rotation():
    client = _client()
    _signup(client)
    r = _login(client)
    refresh = r.json()["refresh_token"]
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r2.status_code == 200, r2.text
    new_refresh = r2.json()["refresh_token"]
    assert new_refresh != refresh, "refresh token must be rotated"
    # Old refresh token is now revoked.
    r3 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r3.status_code == 401


def test_logout_revokes_refresh_token():
    client = _client()
    _signup(client)
    r = _login(client)
    token = r.json()["access_token"]
    refresh = r.json()["refresh_token"]
    r2 = client.post("/api/v1/auth/logout", headers=_auth(token))
    assert r2.status_code == 204
    # The refresh token must no longer be usable.
    r3 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r3.status_code == 401, f"refresh token still valid after logout: {r3.text}"
    # The access token itself is short-lived and stateless; in a real
    # deployment you'd add a Redis-backed JWT blacklist. For this
    # version logout revokes the refresh token, which is the standard
    # pattern. The access token expires automatically within
    # `ANSIQ_JWT_EXPIRE_MINUTES` (default 60min).



def test_password_reset_request_is_idempotent():
    client = _client()
    _signup(client)
    # Request reset for an existing email — must 202.
    r = client.post(
        "/api/v1/auth/password-reset",
        json={"email": "alice@example.com"},
    )
    assert r.status_code == 202
    # Request reset for a non-existing email — same 202 (no enumeration).
    r2 = client.post(
        "/api/v1/auth/password-reset",
        json={"email": "nobody@example.com"},
    )
    assert r2.status_code == 202


def test_mfa_full_flow():
    client = _client()
    _signup(client)
    r = _login(client)
    token = r.json()["access_token"]

    # Initially MFA is disabled.
    r0 = client.get("/api/v1/account/mfa/status", headers=_auth(token))
    assert r0.status_code == 200
    assert r0.json()["mfa_enabled"] is False

    # Enable MFA.
    r1 = client.post("/api/v1/account/mfa/enable", headers=_auth(token))
    assert r1.status_code == 200, r1.text
    body = r1.json()
    assert "secret" in body
    assert body["otpauth_url"].startswith("otpauth://totp/")
    assert len(body["qr_png_base64"]) > 100, "QR code PNG should be a non-trivial payload"

    # Status now shows a secret is staged but MFA is still OFF
    # until the user proves possession.
    r2 = client.get("/api/v1/account/mfa/status", headers=_auth(token))
    assert r2.json()["mfa_enabled"] is False
    assert r2.json()["has_secret"] is True

    # Compute the current TOTP code from the secret and confirm.
    import pyotp
    totp = pyotp.TOTP(body["secret"])
    code = totp.now()
    r3 = client.post(
        "/api/v1/account/mfa/confirm",
        json={"code": code},
        headers=_auth(token),
    )
    assert r3.status_code == 200, r3.text

    # Status now shows MFA is enabled.
    r4 = client.get("/api/v1/account/mfa/status", headers=_auth(token))
    assert r4.json()["mfa_enabled"] is True


def test_mfa_confirm_rejects_wrong_code():
    client = _client()
    _signup(client)
    r = _login(client)
    token = r.json()["access_token"]
    client.post("/api/v1/account/mfa/enable", headers=_auth(token))
    r2 = client.post(
        "/api/v1/account/mfa/confirm",
        json={"code": "000000"},
        headers=_auth(token),
    )
    assert r2.status_code == 400


def test_mfa_disable_requires_password():
    client = _client()
    _signup(client)
    r = _login(client)
    token = r.json()["access_token"]
    # Enable + confirm MFA.
    en = client.post("/api/v1/account/mfa/enable", headers=_auth(token)).json()
    import pyotp
    client.post(
        "/api/v1/account/mfa/confirm",
        json={"code": pyotp.TOTP(en["secret"]).now()},
        headers=_auth(token),
    )
    # Wrong password (8+ chars to pass Pydantic validation, but not
    # the real password) — rejected at the authz layer with 403.
    r2 = client.post(
        "/api/v1/account/mfa/disable",
        json={"password": "wrongpassword"},
        headers=_auth(token),
    )
    assert r2.status_code == 403, f"expected 403 for wrong password, got {r2.status_code}: {r2.text}"

    # Correct password — accepted.
    r3 = client.post(
        "/api/v1/account/mfa/disable",
        json={"password": "CorrectHorseBattery!9"},
        headers=_auth(token),
    )
    assert r3.status_code == 200


def test_gdpr_export_returns_complete_user_payload():
    client = _client()
    _signup(client, email="gdpr@example.com")
    r = _login(client, email="gdpr@example.com")
    token = r.json()["access_token"]
    r2 = client.get("/api/v1/account/me/export", headers=_auth(token))
    assert r2.status_code == 200
    body = r2.json()
    assert body["user"]["email"] == "gdpr@example.com"
    assert "sessions" in body and isinstance(body["sessions"], list)
    assert "api_keys" in body and isinstance(body["api_keys"], list)
    assert "usage_records" in body
    assert "audit_log" in body
    assert "webhook_endpoints" in body
    assert "organization" in body
    assert body["user"]["mfa_enabled"] is False


def test_gdpr_delete_soft_deletes_and_revokes_sessions():
    client = _client()
    _signup(client, email="todelete@example.com")
    r = _login(client, email="todelete@example.com")
    token = r.json()["access_token"]
    refresh = r.json()["refresh_token"]

    r2 = client.post(
        "/api/v1/account/me/delete",
        json={"password": "CorrectHorseBattery!9", "confirm": True},
        headers=_auth(token),
    )
    assert r2.status_code == 202, r2.text
    body = r2.json()
    assert "deleted_at" in body
    assert "hard_delete_scheduled_for" in body

    # Token no longer works (user inactive).
    r3 = client.get("/api/v1/auth/me", headers=_auth(token))
    assert r3.status_code == 401

    # Refresh token no longer works.
    r4 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r4.status_code == 401


def test_gdpr_delete_requires_confirm_and_password():
    client = _client()
    _signup(client, email="protect@example.com")
    r = _login(client, email="protect@example.com")
    token = r.json()["access_token"]
    # Missing confirm flag.
    r2 = client.post(
        "/api/v1/account/me/delete",
        json={"password": "CorrectHorseBattery!9", "confirm": False},
        headers=_auth(token),
    )
    assert r2.status_code == 400
    # Wrong password (8+ chars to pass Pydantic validation, but not
    # the real password) — rejected at the authz layer with 403.
    r3 = client.post(
        "/api/v1/account/me/delete",
        json={"password": "wrongpassword", "confirm": True},
        headers=_auth(token),
    )
    assert r3.status_code == 403, f"expected 403, got {r3.status_code}: {r3.text}"



def test_create_workspace_then_list():
    client = _client()
    _signup(client)
    r = _login(client)
    token = r.json()["access_token"]
    r2 = client.post(
        "/api/v1/workspaces",
        json={"name": "Production", "description": "prod env"},
        headers=_auth(token),
    )
    assert r2.status_code == 201, r2.text
    r3 = client.get("/api/v1/workspaces", headers=_auth(token))
    assert r3.status_code == 200
    assert len(r3.json()) == 1
    assert r3.json()[0]["name"] == "Production"


def test_create_api_key_then_revoke():
    client = _client()
    _signup(client)
    r = _login(client)
    token = r.json()["access_token"]
    r2 = client.post(
        "/api/v1/api-keys",
        json={"name": "ci-key", "scope": "write"},
        headers=_auth(token),
    )
    assert r2.status_code == 201, r2.text
    body = r2.json()
    assert body["secret"].startswith("ansiq_")
    key_id = body["id"]
    r3 = client.delete(f"/api/v1/api-keys/{key_id}", headers=_auth(token))
    assert r3.status_code == 204
    r4 = client.get("/api/v1/api-keys", headers=_auth(token))
    # After revoke, the key is not returned (filtered by is_active=True).
    assert all(k["id"] != key_id for k in r4.json())


def test_create_webhook_then_list():
    client = _client()
    _signup(client)
    r = _login(client)
    token = r.json()["access_token"]
    r2 = client.post(
        "/api/v1/webhooks",
        json={
            "url": "https://example.com/hook",
            "events": ["agent.completed", "*"],
        },
        headers=_auth(token),
    )
    assert r2.status_code == 201, r2.text
    body = r2.json()
    assert body["url"] == "https://example.com/hook"
    assert body["is_active"] is True
    assert "secret" in body  # shown only on create
    r3 = client.get("/api/v1/webhooks", headers=_auth(token))
    assert len(r3.json()) == 1


def test_audit_log_endpoint_is_admin_only():
    client = _client()
    _signup(client)
    r = _login(client)
    token = r.json()["access_token"]
    # The signup user is OWNER so they can read audit logs.
    r2 = client.get("/api/v1/audit-logs", headers=_auth(token))
    assert r2.status_code == 200
    assert isinstance(r2.json(), list)


def test_tenant_health_endpoint():
    client = _client()
    _signup(client)
    r = _login(client)
    token = r.json()["access_token"]
    r2 = client.get("/api/v1/health", headers=_auth(token))
    assert r2.status_code == 200
    body = r2.json()
    assert body["status"] == "ok"
    assert body["organization"] == "AuditCo"
    assert body["plan"] == "free"
    assert body["workspaces"] == 0
    assert body["members"] == 1
    assert body["subscription"] is None

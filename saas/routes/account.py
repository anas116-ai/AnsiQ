"""Account-management endpoints — MFA, GDPR, profile updates.

Mounted under ``/api/v1/account``. Every endpoint requires an
authenticated user; destructive actions are restricted to the user
themselves (or an admin acting on their behalf).
"""

from __future__ import annotations

import base64
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from saas.auth import get_current_user, verify_password
from saas.crypto import decrypt
from saas.database import get_db
from saas.mfa import (
    encrypt_secret,
    generate_secret,
    provisioning_uri,
    qr_code_png,
    verify,
)
from saas.models import (
    ApiKey,
    AuditLog,
    Organization,
    Session,
    UsageRecord,
    User,
    WebhookEndpoint,
)

logger = logging.getLogger("ansiq.saas.routes.account")

router = APIRouter(prefix="/api/v1/account", tags=["Account"])


# ═══════════════════════════════════════════════════════════════════════
# MFA
# ═══════════════════════════════════════════════════════════════════════


class MFAEnableResponse(BaseModel):
    secret: str  # base32; shown ONCE so the user can save it
    otpauth_url: str
    qr_png_base64: str


class MFAConfirmRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=8)


class MFADisableRequest(BaseModel):
    password: str = Field(..., min_length=8, max_length=128)


@router.post("/mfa/enable", response_model=MFAEnableResponse)
async def mfa_enable(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a fresh TOTP secret and provisioning URI.

    MFA is *not* activated until the user calls ``/mfa/confirm`` with a
    valid code from their authenticator app. This protects against an
    attacker enabling MFA on a compromised account.
    """
    if user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="MFA already enabled. Disable first to re-enroll.",
        )
    try:
        secret = generate_secret()
        uri = provisioning_uri(user.email, secret)
        png = qr_code_png(uri)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc))

    # Stash the encrypted secret but leave mfa_enabled=False until confirm.
    user.mfa_secret = encrypt_secret(secret)
    user.mfa_enabled = False  # explicit
    await db.flush()

    return MFAEnableResponse(
        secret=secret,
        otpauth_url=uri,
        qr_png_base64=base64.b64encode(png).decode("ascii"),
    )


@router.post("/mfa/confirm", status_code=status.HTTP_200_OK)
async def mfa_confirm(
    req: MFAConfirmRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Activate MFA after the user proves possession of the TOTP secret."""
    if not user.mfa_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA enrollment not started. Call /mfa/enable first.",
        )
    if user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="MFA already enabled",
        )
    if not verify(user.mfa_secret, req.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TOTP code",
        )
    user.mfa_enabled = True
    await db.flush()
    return {"message": "MFA enabled successfully"}


@router.post("/mfa/disable", status_code=status.HTTP_200_OK)
async def mfa_disable(
    req: MFADisableRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Disable MFA after re-authenticating with the password."""
    if not user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA is not enabled",
        )
    if not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password verification failed",
        )
    user.mfa_enabled = False
    user.mfa_secret = None
    await db.flush()
    return {"message": "MFA disabled"}


@router.get("/mfa/status")
async def mfa_status(user: User = Depends(get_current_user)):
    """Return whether MFA is enabled for the current user."""
    return {
        "mfa_enabled": user.mfa_enabled,
        "has_secret": bool(user.mfa_secret),
    }


# ═══════════════════════════════════════════════════════════════════════
# GDPR — Data Export & Right-to-Erasure
# ═══════════════════════════════════════════════════════════════════════


@router.get("/me/export")
async def export_my_data(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GDPR Article 20 — Data Portability.

    Returns a JSON document containing every row tied to the current
    user (profile, sessions, API keys metadata, usage records, audit
    log entries). Webhook secrets are decrypted for the export then
    delivered once.
    """
    org = await db.get(Organization, user.organization_id)

    sessions = await db.execute(select(Session).where(Session.user_id == user.id))
    keys = await db.execute(select(ApiKey).where(ApiKey.user_id == user.id))
    usage = await db.execute(select(UsageRecord).where(UsageRecord.user_id == user.id))
    audits = await db.execute(select(AuditLog).where(AuditLog.user_id == user.id))
    hooks = await db.execute(
        select(WebhookEndpoint).where(WebhookEndpoint.organization_id == user.organization_id)
    )

    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "format_version": 1,
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role.value,
            "is_active": user.is_active,
            "is_verified": user.is_verified,
            "mfa_enabled": user.mfa_enabled,
            "created_at": user.created_at.isoformat(),
            "last_login_at": (user.last_login_at.isoformat() if user.last_login_at else None),
        },
        "organization": (
            {
                "id": org.id,
                "name": org.name,
                "slug": org.slug,
                "plan": org.plan.value,
            }
            if org
            else None
        ),
        "sessions": [
            {
                "id": s.id,
                "ip_address": s.ip_address,
                "user_agent": s.user_agent,
                "created_at": s.created_at.isoformat(),
                "expires_at": s.expires_at.isoformat(),
                "is_revoked": s.is_revoked,
            }
            for s in sessions.scalars()
        ],
        "api_keys": [
            {
                "id": k.id,
                "name": k.name,
                "key_prefix": k.key_prefix,
                "scope": k.scope.value,
                "created_at": k.created_at.isoformat(),
                "last_used_at": (k.last_used_at.isoformat() if k.last_used_at else None),
            }
            for k in keys.scalars()
        ],
        "usage_records": [
            {
                "id": u.id,
                "metric": u.metric,
                "quantity": u.quantity,
                "recorded_at": u.recorded_at.isoformat(),
            }
            for u in usage.scalars()
        ],
        "audit_log": [
            {
                "id": a.id,
                "action": a.action,
                "resource_type": a.resource_type,
                "resource_id": a.resource_id,
                "severity": a.severity,
                "created_at": a.created_at.isoformat(),
            }
            for a in audits.scalars()
        ],
        "webhook_endpoints": [
            {
                "id": h.id,
                "url": h.url,
                "events": h.events,
                "is_active": h.is_active,
                "secret": decrypt(h.secret),  # Decrypted for export only.
            }
            for h in hooks.scalars()
        ],
    }


class DeleteAccountRequest(BaseModel):
    password: str = Field(..., min_length=8, max_length=128)
    confirm: bool = Field(..., description="Must be true to confirm deletion")


@router.post("/me/delete", status_code=status.HTTP_202_ACCEPTED)
async def delete_my_account(
    req: DeleteAccountRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GDPR Article 17 — Right to Erasure.

    Soft-deletes the user immediately (30-day grace period) and
    schedules a hard-delete job. Sessions are revoked and tokens
    purged so the user is logged out everywhere.
    """
    if not req.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation required",
        )
    if not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password verification failed",
        )
    if user.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account already scheduled for deletion",
        )

    now = datetime.now(UTC)
    user.deleted_at = now
    user.deletion_scheduled_for = now + timedelta(days=30)
    user.is_active = False

    # Revoke all sessions.
    sessions = await db.execute(
        select(Session).where(
            Session.user_id == user.id,
            Session.is_revoked == False,  # noqa: E712
        )
    )
    for s in sessions.scalars():
        s.is_revoked = True
        s.revoked_at = now

    # Deactivate API keys.
    keys = await db.execute(
        select(ApiKey).where(
            ApiKey.user_id == user.id,
            ApiKey.is_active == True,  # noqa: E712
        )
    )
    for k in keys.scalars():
        k.is_active = False

    # Audit the deletion.
    db.add(
        AuditLog(
            organization_id=user.organization_id,
            user_id=user.id,
            action="user.deleted",
            resource_type="user",
            resource_id=user.id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            severity="warning",
            details={"scheduled_hard_delete_at": user.deletion_scheduled_for.isoformat()},
        )
    )
    await db.flush()

    return {
        "message": "Account scheduled for deletion",
        "deleted_at": user.deleted_at.isoformat(),
        "hard_delete_scheduled_for": user.deletion_scheduled_for.isoformat(),
    }

"""Authentication API routes — signup, login, logout, token refresh,
email verification, password reset.

All email sends are scheduled in the background so a slow SMTP server
cannot block the originating HTTP request.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from saas.auth import (
    authenticate_user,
    create_session,
    create_user,
    get_current_user,
    hash_password,
)
from saas.database import get_db
from saas.email import email_service
from saas.models import (
    EmailVerificationToken,
    PasswordResetToken,
    Session,
    User,
)

logger = logging.getLogger("ansiq.saas.routes.auth")

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


# ── Schemas ────────────────────────────────────────────────────────────


class SignupRequest(BaseModel):
    email: str
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=1, max_length=255)
    org_name: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class PasswordResetRequest(BaseModel):
    email: str


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8, max_length=128)


class VerifyEmailRequest(BaseModel):
    token: str


# ── Routes ─────────────────────────────────────────────────────────────


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    req: SignupRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Register a new user + organization and email a verification link."""
    user, org = await create_user(db, req.email, req.password, req.full_name, req.org_name)
    access_token, refresh_token = await create_session(
        db,
        user,
        ip=request.client.host if request.client else None,
        ua=request.headers.get("user-agent"),
    )

    # Create a real verification token, persist its hash, and email the
    # raw token to the user.
    raw, token_hash = EmailVerificationToken.new_token()
    db.add(
        EmailVerificationToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
    )
    await db.flush()

    # Fire-and-forget email — do not block the response on SMTP.
    asyncio.create_task(email_service.send_verification_email(user.email, raw))

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/login", response_model=TokenResponse)
async def login(
    req: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate user and return tokens."""
    user = await authenticate_user(db, req.email, req.password)
    access_token, refresh_token = await create_session(
        db,
        user,
        ip=request.client.host if request.client else None,
        ua=request.headers.get("user-agent"),
    )
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a refresh token for new access + refresh tokens."""
    token_hash = hashlib.sha256(req.refresh_token.encode()).hexdigest()
    now = datetime.now(UTC)
    result = await db.execute(
        select(Session).where(
            Session.refresh_token_hash == token_hash,
            Session.is_revoked == False,  # noqa: E712
            Session.expires_at > now,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # Revoke old session
    session.is_revoked = True
    session.revoked_at = datetime.now(UTC)

    # Get user (also enforces tenant scoping through organization_id).
    user_result = await db.execute(
        select(User).where(
            User.id == session.user_id,
            User.is_active == True,  # noqa: E712
        )
    )
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    new_access, new_refresh = await create_session(db, user)
    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke all sessions for the current user."""
    result = await db.execute(
        select(Session).where(
            Session.user_id == user.id,
            Session.is_revoked == False,  # noqa: E712
        )
    )
    revoked_at = datetime.now(UTC)
    for session in result.scalars():
        session.is_revoked = True
        session.revoked_at = revoked_at
    await db.flush()


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    """Get current user profile."""
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role.value,
        "org_id": user.organization_id,
        "is_verified": user.is_verified,
        "created_at": user.created_at.isoformat(),
    }


@router.post("/password-reset", status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(
    req: PasswordResetRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Send password reset email.

    Always returns the same generic response to prevent user-enumeration
    attacks, regardless of whether the email is registered.
    """
    response = {"message": "If the email exists, a reset link has been sent"}

    result = await db.execute(select(User).where(User.email == req.email.lower().strip()))
    user = result.scalar_one_or_none()
    if user and user.is_active:
        raw, token_hash = PasswordResetToken.new_token()
        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                ip_address=request.client.host if request.client else None,
            )
        )
        await db.flush()
        asyncio.create_task(email_service.send_password_reset(user.email, raw))

    return response


@router.post("/password-reset/confirm", status_code=status.HTTP_200_OK)
async def confirm_password_reset(req: PasswordResetConfirm, db: AsyncSession = Depends(get_db)):
    """Consume a password-reset token and set a new password."""
    token_hash = hashlib.sha256(req.token.encode()).hexdigest()
    now = datetime.now(UTC)
    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.is_used == False,  # noqa: E712
            PasswordResetToken.expires_at > now,
        )
    )
    reset = result.scalar_one_or_none()
    if not reset:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    user_result = await db.execute(select(User).where(User.id == reset.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    user.password_hash = hash_password(req.new_password)
    reset.is_used = True
    reset.used_at = now

    # Invalidate all existing sessions for safety.
    sessions_result = await db.execute(
        select(Session).where(
            Session.user_id == user.id,
            Session.is_revoked == False,  # noqa: E712
        )
    )
    for s in sessions_result.scalars():
        s.is_revoked = True
        s.revoked_at = now

    return {"message": "Password updated successfully"}


@router.post("/verify-email", status_code=status.HTTP_200_OK)
async def verify_email(req: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    """Consume an email-verification token and mark the user verified."""
    token_hash = hashlib.sha256(req.token.encode()).hexdigest()
    now = datetime.now(UTC)
    result = await db.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == token_hash,
            EmailVerificationToken.is_used == False,  # noqa: E712
            EmailVerificationToken.expires_at > now,
        )
    )
    verify = result.scalar_one_or_none()
    if not verify:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )

    user_result = await db.execute(select(User).where(User.id == verify.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )

    user.is_verified = True
    verify.is_used = True
    verify.used_at = now
    return {"message": "Email verified successfully"}

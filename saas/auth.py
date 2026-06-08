"""Authentication service — JWT, password hashing, login/signup, verification."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt as pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from saas.config import config
from saas.database import get_db
from saas.models import Organization, OrgPlan, Session, User, UserRole

logger = logging.getLogger("ansiq.saas.auth")

security = HTTPBearer(auto_error=False)


# ── Password Hashing (bcrypt) ──────────────────────────────────────────
#
# bcrypt is the industry-standard adaptive password hashing algorithm.
# It is intentionally slow (cost factor ≈ 2^12 ≈ 250ms per hash on modern
# CPUs) which makes brute-force and rainbow-table attacks impractical.
#
# Passwords are NEVER stored in plaintext. We only store the bcrypt hash
# which already includes a per-password random salt internally, so there
# is no need to manage salts separately.


def hash_password(password: str) -> str:
    """Hash a password with bcrypt using the configured cost factor.

    The returned string is the full PHC-formatted bcrypt hash including
    the version, cost, salt and digest (≈ 60 chars). It is safe to store
    directly in the ``users.password_hash`` column (String(255)).
    """
    if not password:
        raise ValueError("password must not be empty")
    # bcrypt has a hard 72-byte input limit; pre-hash longer passwords
    # with SHA-256 to allow arbitrary-length passphrases while keeping
    # the bcrypt protection against brute-force.
    if len(password.encode("utf-8")) > 72:
        password = hashlib.sha256(password.encode("utf-8")).hexdigest()
    rounds = max(4, min(15, int(config.security.bcrypt_rounds)))
    salt = bcrypt.gensalt(rounds=rounds)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, stored: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    if not stored or not password:
        return False
    try:
        if len(password.encode("utf-8")) > 72:
            password = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed hash (e.g., legacy SHA-256 "$salt$hash" format) — fail
        # closed so callers treat the user as unauthenticated.
        return False


# ── JWT Tokens ──────────────────────────────────────────────────────────


def create_access_token(user_id: str, org_id: str, role: str) -> str:
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=config.security.jwt_expire_minutes)
    payload = {
        "sub": user_id,
        "org": org_id,
        "role": role,
        # PyJWT requires exp/iat as integer Unix timestamps (NOT datetime objects)
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
        "type": "access",
    }
    return pyjwt.encode(
        payload,
        config.security.jwt_secret,
        algorithm=config.security.jwt_algorithm,
    )


def create_refresh_token() -> tuple[str, str]:
    """Generate a refresh token and its hash."""
    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    return token, token_hash


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises HTTPException on failure."""
    try:
        payload = pyjwt.decode(
            token,
            config.security.jwt_secret,
            algorithms=[config.security.jwt_algorithm],
        )
        # Require sub claim — fail closed if missing or wrong type.
        if not isinstance(payload, dict) or "sub" not in payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        return payload
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


# ── Auth Dependency ─────────────────────────────────────────────────────


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """FastAPI dependency: extract and validate current user from JWT."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token(credentials.credentials)
    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user


async def require_role(required_role: UserRole):
    """Dependency factory: require minimum role."""

    async def _check(user: User = Depends(get_current_user)) -> User:
        role_rank = {
            UserRole.VIEWER: 0,
            UserRole.MEMBER: 1,
            UserRole.ADMIN: 2,
            UserRole.OWNER: 3,
        }
        if role_rank.get(user.role, -1) < role_rank.get(required_role, 0):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return user

    return _check


# ── Signup / Login ──────────────────────────────────────────────────────


async def create_organization(db: AsyncSession, name: str) -> Organization:
    """Create a new organization (tenant)."""
    slug_base = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
    if not slug_base:
        slug_base = "org"
    slug = f"{slug_base}-{secrets.token_hex(4)}"
    org = Organization(
        name=name,
        slug=slug,
        plan=OrgPlan.FREE,
        trial_ends_at=datetime.now(UTC) + timedelta(days=14),
    )
    db.add(org)
    await db.flush()
    return org


async def create_user(
    db: AsyncSession,
    email: str,
    password: str,
    full_name: str,
    org_name: str | None = None,
) -> tuple[User, Organization]:
    """Register a new user with a new organization."""
    email_normalized = email.strip().lower()
    # Check duplicate email
    result = await db.execute(select(User).where(User.email == email_normalized))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    org = await create_organization(db, org_name or f"{full_name}'s Org")
    user = User(
        email=email_normalized,
        password_hash=hash_password(password),
        full_name=full_name,
        organization_id=org.id,
        role=UserRole.OWNER,
        is_verified=False,
    )
    db.add(user)
    await db.flush()
    return user, org


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User:
    """Verify credentials and return user."""
    email_normalized = email.strip().lower()
    result = await db.execute(select(User).where(User.email == email_normalized))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        # Generic error to prevent user-enumeration attacks.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )
    return user


async def create_session(
    db: AsyncSession,
    user: User,
    ip: str | None = None,
    ua: str | None = None,
) -> tuple[str, str]:
    """Create access + refresh tokens for a user."""
    access_token = create_access_token(user.id, user.organization_id, user.role.value)
    refresh_token, token_hash = create_refresh_token()

    session = Session(
        user_id=user.id,
        refresh_token_hash=token_hash,
        ip_address=ip,
        user_agent=ua,
        expires_at=datetime.now(UTC) + timedelta(days=config.security.jwt_refresh_expire_days),
    )
    db.add(session)
    user.last_login_at = datetime.now(UTC)
    await db.flush()

    return access_token, refresh_token

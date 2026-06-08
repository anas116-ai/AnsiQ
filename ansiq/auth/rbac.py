"""RBAC Manager — role-based access control with user management.

Provides:
- Centralized user and role management
- Permission checking
- User CRUD with disk persistence
- Session token generation and validation
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any

from ansiq.auth.models import (
    Permission,
    Role,
    Session,
    User,
)

logger = logging.getLogger(__name__)


class AccessDenied(Exception):
    """Raised when a user lacks the required permission."""

    def __init__(self, user_id: str, permission: str, resource: str = ""):
        self.user_id = user_id
        self.permission = permission
        self.resource = resource
        msg = f"Access denied: user '{user_id}' lacks permission '{permission}'"
        if resource:
            msg += f" on '{resource}'"
        super().__init__(msg)


class RBACManager:
    """Role-Based Access Control manager.

    Central authority for:
    - Creating and managing users
    - Authenticating users (password + SSO)
    - Creating and validating sessions
    - Checking permissions
    - Audit trail

    Usage:
        rbac = RBACManager()

        # Create user
        user = rbac.create_user(email="alice@acme.com", password="secret")

        # Authenticate
        session = rbac.authenticate(email="alice@acme.com", password="secret")

        # Check permission
        rbac.check_permission(session.id, Permission.AGENT_CREATE)
    """

    def __init__(
        self,
        storage_path: Path | str | None = None,
        session_ttl_hours: int = 24,
        max_sessions_per_user: int = 5,
    ):
        self.storage_path = Path(storage_path or Path.home() / ".ansiq" / "auth")
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.session_ttl_hours = session_ttl_hours
        self.max_sessions_per_user = max_sessions_per_user

        self._users: dict[str, User] = {}
        self._sessions: dict[str, Session] = {}
        self._email_index: dict[str, str] = {}  # email -> user_id

        self._load()
        self._ensure_super_admin()

    def _ensure_super_admin(self) -> None:
        """Ensure at least one super_admin exists."""
        has_super = any(u.role == Role.SUPER_ADMIN for u in self._users.values())
        if not has_super and self._users:
            # Upgrade first user to super_admin
            first_user = list(self._users.values())[0]
            first_user.role = Role.SUPER_ADMIN
            logger.info("Auto-promoted '%s' to SUPER_ADMIN", first_user.email)
            self._save()

    # ── User Management ──

    def create_user(
        self,
        email: str,
        password: str = "",
        username: str = "",
        role: Role = Role.MEMBER,
        sso_provider: str | None = None,
        sso_id: str | None = None,
        organization_id: str | None = None,
    ) -> User:
        """Create a new user."""
        email_lower = email.lower().strip()

        if email_lower in self._email_index:
            raise ValueError(f"User with email '{email}' already exists")

        user = User(
            email=email_lower,
            username=username or email_lower.split("@")[0],
            display_name=username or email_lower.split("@")[0],
            role=role,
            sso_provider=sso_provider,
            sso_id=sso_id,
            organization_id=organization_id,
        )

        if password:
            user.set_password(password)

        self._users[user.id] = user
        self._email_index[email_lower] = user.id
        self._save()

        logger.info("Created user '%s' (%s) with role %s", user.email, user.id, role.value)
        return user

    def get_user(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    def get_user_by_email(self, email: str) -> User | None:
        user_id = self._email_index.get(email.lower().strip())
        if user_id:
            return self._users.get(user_id)
        return None

    def list_users(
        self,
        organization_id: str | None = None,
        role: Role | None = None,
        active_only: bool = True,
    ) -> list[User]:
        users = list(self._users.values())
        if active_only:
            users = [u for u in users if u.active]
        if organization_id:
            users = [u for u in users if u.organization_id == organization_id]
        if role:
            users = [u for u in users if u.role == role]
        return sorted(users, key=lambda u: u.created_at)

    def update_user(self, user_id: str, **kwargs: Any) -> User | None:
        user = self._users.get(user_id)
        if not user:
            return None

        for key, value in kwargs.items():
            if key == "password":
                user.set_password(value)
            elif hasattr(user, key):
                setattr(user, key, value)

        self._save()
        return user

    def delete_user(self, user_id: str) -> bool:
        user = self._users.pop(user_id, None)
        if user:
            self._email_index.pop(user.email, None)
            self._save()
            logger.info("Deleted user %s (%s)", user.email, user_id)
            return True
        return False

    # ── Authentication ──

    def authenticate(
        self,
        email: str,
        password: str = "",
        ip_address: str = "",
        user_agent: str = "",
    ) -> Session | None:
        """Authenticate with email/password. Returns a session on success."""
        user = self.get_user_by_email(email)
        if not user or not user.active:
            return None

        if password and not user.verify_password(password):
            logger.warning("Failed login attempt for %s", email)
            return None

        # Create session
        session = self._create_session(user, ip_address, user_agent)

        # Update last login
        user.last_login_at = time.time()
        user.last_login_ip = ip_address
        self._save()

        logger.info("User '%s' authenticated successfully", email)
        return session

    def authenticate_sso(
        self,
        provider: str,
        sso_id: str,
        email: str,
        display_name: str = "",
        ip_address: str = "",
        user_agent: str = "",
    ) -> Session | None:
        """Authenticate via SSO provider."""
        user = self.get_user_by_email(email)

        if not user:
            # Auto-create user from SSO
            user = self.create_user(
                email=email,
                username=display_name or email.split("@")[0],
                sso_provider=provider,
                sso_id=sso_id,
            )
        elif user.sso_provider != provider:
            # User exists but with different auth method
            logger.warning("SSO provider mismatch for %s", email)
            return None

        session = self._create_session(user, ip_address, user_agent)
        user.last_login_at = time.time()
        user.last_login_ip = ip_address
        self._save()

        return session

    def _create_session(
        self,
        user: User,
        ip_address: str = "",
        user_agent: str = "",
    ) -> Session:
        """Create a new session for a user."""
        # Enforce max sessions per user
        user_sessions = [s for s in self._sessions.values() if s.user_id == user.id and s.active]
        if len(user_sessions) >= self.max_sessions_per_user:
            # Revoke oldest session
            oldest = min(user_sessions, key=lambda s: s.created_at)
            oldest.revoke()

        # Generate token
        raw_token = f"ansiq_token_{secrets.token_urlsafe(32)}"
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

        session = Session(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=time.time() + self.session_ttl_hours * 3600,
            ip_address=ip_address,
            user_agent=user_agent,
            organization_id=user.organization_id,
        )

        self._sessions[session.id] = session
        self._save()

        return session

    def validate_session(self, session_id: str) -> Session | None:
        """Validate a session and return it if valid."""
        session = self._sessions.get(session_id)
        if session and session.is_valid:
            session.touch()
            return session
        return None

    def validate_token(self, token_hash: str) -> Session | None:
        """Validate by token hash."""
        for session in self._sessions.values():
            if session.token_hash == token_hash and session.is_valid:
                session.touch()
                return session
        return None

    def revoke_session(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if session:
            session.revoke()
            self._save()
            return True
        return False

    def revoke_all_user_sessions(self, user_id: str) -> int:
        count = 0
        for session in self._sessions.values():
            if session.user_id == user_id and session.active:
                session.revoke()
                count += 1
        if count > 0:
            self._save()
        return count

    # ── Permission Checking ──

    def check_permission(self, session_id: str, permission: Permission) -> bool:
        """Check if a session's user has a specific permission."""
        session = self.validate_session(session_id)
        if not session:
            return False

        user = self.get_user(session.user_id)
        if not user or not user.active:
            return False

        return user.has_permission(permission)

    def require_permission(self, session_id: str, permission: Permission) -> None:
        """Check permission and raise AccessDenied if denied."""
        session = self.validate_session(session_id)
        if not session:
            raise AccessDenied("anonymous", permission.value, "session")

        user = self.get_user(session.user_id)
        if not user or not user.active:
            raise AccessDenied(session.user_id, permission.value, "user_inactive")

        if not user.has_permission(permission):
            raise AccessDenied(session.user_id, permission.value)

    def get_user_from_session(self, session_id: str) -> User | None:
        """Get the user for a valid session."""
        session = self.validate_session(session_id)
        if session:
            return self.get_user(session.user_id)
        return None

    # ── Persistence ──

    def _save(self) -> None:
        """Save users and sessions to disk."""
        try:
            users_data = []
            for user in self._users.values():
                d = {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
                    "display_name": user.display_name,
                    "password_hash": user.password_hash,
                    "password_salt": user.password_salt,
                    "role": user.role.value,
                    "custom_permissions": [p.value for p in user.custom_permissions],
                    "active": user.active,
                    "email_verified": user.email_verified,
                    "mfa_enabled": user.mfa_enabled,
                    "sso_provider": user.sso_provider,
                    "sso_id": user.sso_id,
                    "organization_id": user.organization_id,
                    "workspace_ids": user.workspace_ids,
                    "created_at": user.created_at,
                    "last_login_at": user.last_login_at,
                    "last_login_ip": user.last_login_ip,
                }
                users_data.append(d)

            sessions_data = []
            for session in self._sessions.values():
                if session.active:
                    sessions_data.append(
                        {
                            "id": session.id,
                            "user_id": session.user_id,
                            "token_hash": session.token_hash,
                            "created_at": session.created_at,
                            "expires_at": session.expires_at,
                            "last_active_at": session.last_active_at,
                            "ip_address": session.ip_address,
                            "user_agent": session.user_agent,
                            "organization_id": session.organization_id,
                            "workspace_id": session.workspace_id,
                            "scopes": session.scopes,
                            "active": session.active,
                        }
                    )

            path = self.storage_path / "auth.json"
            path.write_text(json.dumps({"users": users_data, "sessions": sessions_data}, indent=2))
        except Exception as e:
            logger.debug("Failed to save auth data: %s", e)

    def _load(self) -> None:
        """Load users and sessions from disk."""
        try:
            path = self.storage_path / "auth.json"
            if not path.exists():
                return

            data = json.loads(path.read_text())

            # Build a lookup of valid Permission values to filter out
            # unknown / renamed permission strings safely.
            valid_permissions = {p.value for p in Permission}

            for d in data.get("users", []):
                # Safely load permissions — skip unknown ones
                custom_perms_raw = d.get("custom_permissions", []) or []
                custom_perms: list[Permission] = []
                for p in custom_perms_raw:
                    try:
                        if p in valid_permissions:
                            custom_perms.append(Permission(p))
                    except (ValueError, KeyError):
                        # Silently drop unknown permission values
                        continue

                # Safely load role — fall back to MEMBER if unknown
                try:
                    role = Role(d.get("role", "member"))
                except ValueError:
                    role = Role.MEMBER

                user = User(
                    id=d["id"],
                    email=d["email"],
                    username=d.get("username", ""),
                    display_name=d.get("display_name", ""),
                    password_hash=d.get("password_hash", ""),
                    password_salt=d.get("password_salt", ""),
                    role=role,
                    custom_permissions=custom_perms,
                    active=d.get("active", True),
                    email_verified=d.get("email_verified", False),
                    mfa_enabled=d.get("mfa_enabled", False),
                    sso_provider=d.get("sso_provider"),
                    sso_id=d.get("sso_id"),
                    organization_id=d.get("organization_id"),
                    workspace_ids=d.get("workspace_ids", []),
                    created_at=d.get("created_at", time.time()),
                    last_login_at=d.get("last_login_at"),
                    last_login_ip=d.get("last_login_ip"),
                )
                self._users[user.id] = user
                self._email_index[user.email] = user.id

            for d in data.get("sessions", []):
                try:
                    session = Session(**d)
                    self._sessions[session.id] = session
                except Exception:
                    # Skip malformed session records
                    continue

        except Exception as e:
            logger.debug("Failed to load auth data: %s", e)

    def get_stats(self) -> dict[str, Any]:
        """Get authentication statistics."""
        return {
            "users": len(self._users),
            "active_users": len([u for u in self._users.values() if u.active]),
            "active_sessions": len([s for s in self._sessions.values() if s.is_valid]),
            "by_role": {
                role.value: len([u for u in self._users.values() if u.role == role])
                for role in Role
            },
        }

    def __repr__(self) -> str:
        return f"RBACManager(users={len(self._users)}, sessions={len(self._sessions)})"

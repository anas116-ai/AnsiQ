"""Auth Models — User, Role, Permission, Session data structures.

Clean, auditable models for multi-user authentication.
"""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Permission(StrEnum):
    """Granular permissions for agent actions."""

    # Agent permissions
    AGENT_CREATE = "agent:create"
    AGENT_READ = "agent:read"
    AGENT_UPDATE = "agent:update"
    AGENT_DELETE = "agent:delete"
    AGENT_EXECUTE = "agent:execute"

    # Crew permissions
    CREW_CREATE = "crew:create"
    CREW_READ = "crew:read"
    CREW_UPDATE = "crew:update"
    CREW_DELETE = "crew:delete"
    CREW_EXECUTE = "crew:execute"

    # Task permissions
    TASK_CREATE = "task:create"
    TASK_READ = "task:read"
    TASK_UPDATE = "task:update"
    TASK_DELETE = "task:delete"
    TASK_EXECUTE = "task:execute"

    # Tool permissions
    TOOL_READ = "tool:read"
    TOOL_REGISTER = "tool:register"
    TOOL_DELETE = "tool:delete"

    # Memory permissions
    MEMORY_READ = "memory:read"
    MEMORY_WRITE = "memory:write"
    MEMORY_DELETE = "memory:delete"

    # Knowledge permissions
    KNOWLEDGE_READ = "knowledge:read"
    KNOWLEDGE_WRITE = "knowledge:write"

    # Sandbox permissions
    SANDBOX_EXECUTE = "sandbox:execute"
    SANDBOX_CONFIGURE = "sandbox:configure"

    # API permissions
    API_KEY_CREATE = "api_key:create"
    API_KEY_REVOKE = "api_key:revoke"

    # Admin permissions
    ADMIN_MANAGE_USERS = "admin:manage_users"
    ADMIN_MANAGE_ORG = "admin:manage_org"
    ADMIN_VIEW_AUDIT = "admin:view_audit"
    ADMIN_MANAGE_BILLING = "admin:manage_billing"

    # Read-only
    DASHBOARD_VIEW = "dashboard:view"
    ANALYTICS_VIEW = "analytics:view"

    # Scope: workspace
    WORKSPACE_READ = "workspace:read"
    WORKSPACE_UPDATE = "workspace:update"


class Role(StrEnum):
    """Built-in roles with predefined permission sets."""

    SUPER_ADMIN = "super_admin"
    """Full system access."""

    ADMIN = "admin"
    """Organization-level management."""

    MEMBER = "member"
    """Standard user with agent/crew/task access."""

    VIEWER = "viewer"
    """Read-only access."""

    CUSTOM = "custom"
    """Custom role with explicit permissions."""


# ── Default permission sets for each role ──

ROLE_PERMISSIONS: dict[Role, list[Permission]] = {
    Role.SUPER_ADMIN: list(Permission),
    Role.ADMIN: [
        Permission.AGENT_CREATE,
        Permission.AGENT_READ,
        Permission.AGENT_UPDATE,
        Permission.AGENT_DELETE,
        Permission.AGENT_EXECUTE,
        Permission.CREW_CREATE,
        Permission.CREW_READ,
        Permission.CREW_UPDATE,
        Permission.CREW_DELETE,
        Permission.CREW_EXECUTE,
        Permission.TASK_CREATE,
        Permission.TASK_READ,
        Permission.TASK_UPDATE,
        Permission.TASK_DELETE,
        Permission.TASK_EXECUTE,
        Permission.TOOL_READ,
        Permission.TOOL_REGISTER,
        Permission.MEMORY_READ,
        Permission.MEMORY_WRITE,
        Permission.KNOWLEDGE_READ,
        Permission.KNOWLEDGE_WRITE,
        Permission.SANDBOX_EXECUTE,
        Permission.API_KEY_CREATE,
        Permission.API_KEY_REVOKE,
        Permission.ADMIN_MANAGE_USERS,
        Permission.ADMIN_MANAGE_ORG,
        Permission.ADMIN_VIEW_AUDIT,
        Permission.ADMIN_MANAGE_BILLING,
        Permission.DASHBOARD_VIEW,
        Permission.ANALYTICS_VIEW,
        Permission.WORKSPACE_READ,
        Permission.WORKSPACE_UPDATE,
    ],
    Role.MEMBER: [
        Permission.AGENT_CREATE,
        Permission.AGENT_READ,
        Permission.AGENT_UPDATE,
        Permission.AGENT_EXECUTE,
        Permission.CREW_CREATE,
        Permission.CREW_READ,
        Permission.CREW_UPDATE,
        Permission.CREW_EXECUTE,
        Permission.TASK_CREATE,
        Permission.TASK_READ,
        Permission.TASK_UPDATE,
        Permission.TASK_EXECUTE,
        Permission.TOOL_READ,
        Permission.MEMORY_READ,
        Permission.MEMORY_WRITE,
        Permission.KNOWLEDGE_READ,
        Permission.SANDBOX_EXECUTE,
        Permission.DASHBOARD_VIEW,
        Permission.ANALYTICS_VIEW,
        Permission.WORKSPACE_READ,
    ],
    Role.VIEWER: [
        Permission.AGENT_READ,
        Permission.CREW_READ,
        Permission.TASK_READ,
        Permission.TOOL_READ,
        Permission.MEMORY_READ,
        Permission.KNOWLEDGE_READ,
        Permission.DASHBOARD_VIEW,
        Permission.ANALYTICS_VIEW,
        Permission.WORKSPACE_READ,
    ],
    Role.CUSTOM: [],
}


class User(BaseModel):
    """A user in the system."""

    id: str = Field(default_factory=lambda: f"usr_{uuid.uuid4().hex[:12]}")

    email: str = ""
    username: str = ""
    display_name: str = ""

    # Password (hashed — never stored as plaintext)
    password_hash: str = ""
    password_salt: str = ""

    # SSO
    sso_provider: str | None = None
    """'google', 'github', 'microsoft', or None for password auth."""
    sso_id: str | None = None
    """External SSO user ID."""

    # Role
    role: Role = Role.MEMBER
    custom_permissions: list[Permission] = Field(default_factory=list)

    # Status
    active: bool = True
    email_verified: bool = False
    mfa_enabled: bool = False

    # Metadata
    created_at: float = Field(default_factory=time.time)
    last_login_at: float | None = None
    last_login_ip: str | None = None

    # Workspace membership
    organization_id: str | None = None
    workspace_ids: list[str] = Field(default_factory=list)

    def has_permission(self, permission: Permission) -> bool:
        """Check if user has a specific permission."""
        # Super admin has everything
        if self.role == Role.SUPER_ADMIN:
            return True

        # Check role-based permissions
        if permission in ROLE_PERMISSIONS.get(self.role, []):
            return True

        # Check custom permissions
        if permission in self.custom_permissions:
            return True

        return False

    def has_any_permission(self, permissions: list[Permission]) -> bool:
        """Check if user has ANY of the given permissions."""
        return any(self.has_permission(p) for p in permissions)

    def has_all_permissions(self, permissions: list[Permission]) -> bool:
        """Check if user has ALL of the given permissions."""
        return all(self.has_permission(p) for p in permissions)

    def get_all_permissions(self) -> list[Permission]:
        """Get all permissions for this user."""
        base = set(ROLE_PERMISSIONS.get(self.role, []))
        base.update(self.custom_permissions)
        if self.role == Role.SUPER_ADMIN:
            base = set(Permission)
        return sorted(base, key=lambda p: p.value)

    def set_password(self, password: str) -> None:
        """Hash and set a new password with bcrypt (cost 12).

        bcrypt is the industry-standard adaptive hash: ~250ms per hash
        at cost=12 makes brute-force impractical. Bcrypt has a hard
        72-byte input limit; we pre-hash longer inputs with SHA-256 to
        allow arbitrary-length passphrases.
        """
        import bcrypt

        # bcrypt has a hard 72-byte input limit
        if len(password.encode("utf-8")) > 72:
            password = hashlib.sha256(password.encode("utf-8")).hexdigest()
        salt = bcrypt.gensalt(rounds=12)
        self.password_hash = bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")
        # Keep the legacy salt field populated for backward compat
        # with any persisted fixtures; the value is irrelevant for
        # bcrypt-verified accounts.
        self.password_salt = salt.decode("utf-8")

    def verify_password(self, password: str) -> bool:
        """Verify a plaintext password against the stored hash.

        Supports both the new bcrypt PHC strings and the legacy SHA-256
        ``salt:hash`` format for backwards compatibility with existing
        JSON persistence files.
        """
        if not self.password_hash:
            return False
        if not password:
            return False
        # New bcrypt format
        if self.password_hash.startswith(("$2a$", "$2b$", "$2y$")):
            try:
                import bcrypt

                if len(password.encode("utf-8")) > 72:
                    password = hashlib.sha256(password.encode("utf-8")).hexdigest()
                return bcrypt.checkpw(
                    password.encode("utf-8"),
                    self.password_hash.encode("utf-8"),
                )
            except (ValueError, TypeError):
                return False
        # Legacy SHA-256 ``salt$hash`` format
        try:
            if ":" in self.password_salt:
                salt = self.password_salt
            else:
                salt, _ = self.password_hash.split("$", 1)
            computed = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
            return secrets.compare_digest(computed, self.password_hash)
        except (ValueError, TypeError, AttributeError):
            return False

    def to_public_dict(self) -> dict[str, Any]:
        """Export user without sensitive fields."""
        return {
            "id": self.id,
            "email": self.email,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role.value,
            "active": self.active,
            "organization_id": self.organization_id,
            "workspace_ids": self.workspace_ids,
            "created_at": self.created_at,
            "last_login_at": self.last_login_at,
        }


class Session(BaseModel):
    """An authenticated user session."""

    id: str = Field(default_factory=lambda: f"sess_{uuid.uuid4().hex[:12]}")
    user_id: str = ""

    # Token
    token_hash: str = ""
    """SHA-256 hash of the JWT or session token."""

    # Timing
    created_at: float = Field(default_factory=time.time)
    expires_at: float = 0
    last_active_at: float = Field(default_factory=time.time)

    # Context
    ip_address: str = ""
    user_agent: str = ""

    # Scope
    organization_id: str | None = None
    workspace_id: str | None = None
    scopes: list[str] = Field(default_factory=list)

    # Status
    active: bool = True

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    @property
    def is_valid(self) -> bool:
        return self.active and not self.is_expired

    @property
    def ttl_seconds(self) -> float:
        """Time until session expires."""
        return max(0, self.expires_at - time.time())

    def touch(self) -> None:
        """Update last active timestamp."""
        self.last_active_at = time.time()

    def revoke(self) -> None:
        """Revoke this session."""
        self.active = False

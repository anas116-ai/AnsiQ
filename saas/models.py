"""Production-grade SQLAlchemy models for the AnsiQ SaaS platform.

Domain entities:
  - Organization, Workspace, Team
  - User, Session, ApiKey
  - Subscription, Invoice, UsageRecord
  - WebhookEndpoint, WebhookEvent
  - AuditLog
  - EmailVerificationToken, PasswordResetToken
"""

from __future__ import annotations

import secrets
from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from saas.database import Base

# ══════════════════════════════════════════════════════════════════════════
# Enums
# ══════════════════════════════════════════════════════════════════════════


class OrgPlan(StrEnum):
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    INCOMPLETE = "incomplete"
    INCOMPLETE_EXPIRED = "incomplete_expired"
    TRIALING = "trialing"
    PAUSED = "paused"
    UNPAID = "unpaid"


class UserRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class ApiKeyScope(StrEnum):
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


class WebhookEventType(StrEnum):
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    TASK_COMPLETED = "task.completed"
    WORKFLOW_COMPLETED = "workflow.completed"
    INVOICE_PAID = "invoice.paid"
    SUBSCRIPTION_UPDATED = "subscription.updated"
    USER_CREATED = "user.created"


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    PAID = "paid"
    VOID = "void"
    UNCOLLECTIBLE = "uncollectible"


# ══════════════════════════════════════════════════════════════════════════
# Organization & Workspace
# ══════════════════════════════════════════════════════════════════════════


class Organization(Base):
    """Top-level tenant entity."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    plan: Mapped[OrgPlan] = mapped_column(Enum(OrgPlan), default=OrgPlan.FREE)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    billing_email: Mapped[str | None] = mapped_column(String(255))
    billing_address: Mapped[dict | None] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    max_users: Mapped[int] = mapped_column(Integer, default=5)
    max_workspaces: Mapped[int] = mapped_column(Integer, default=2)
    max_tasks_per_month: Mapped[int] = mapped_column(Integer, default=1000)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    workspaces: Mapped[list[Workspace]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    users: Mapped[list[User]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    subscriptions: Mapped[list[Subscription]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    agents: Mapped[list[Agent]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    crews: Mapped[list[CrewModel]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Organization {self.slug} ({self.plan.value})>"


class Workspace(Base):
    """A workspace/project within an organization."""

    __tablename__ = "workspaces"

    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    settings: Mapped[dict | None] = mapped_column(JSON, default=dict)

    # Relationships
    organization: Mapped[Organization] = relationship(back_populates="workspaces")

    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_workspace_org_slug"),)

    def __repr__(self) -> str:
        return f"<Workspace {self.slug}>"


class Agent(Base):
    """AI Agent configuration within a SaaS organization."""

    __tablename__ = "agents"

    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workspaces.id")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g., gpt-4, claude-3
    instructions: Mapped[str | None] = mapped_column(Text)
    temperature: Mapped[float] = mapped_column(default=0.7)
    max_tokens: Mapped[int] = mapped_column(default=4096)
    tools: Mapped[list | None] = mapped_column(JSON, default=list)
    system_prompt: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    settings: Mapped[dict | None] = mapped_column(JSON, default=dict)
    agent_metadata: Mapped[dict | None] = mapped_column(JSON, default=dict)

    # Relationships
    organization: Mapped[Organization] = relationship(back_populates="agents")

    # Indexes for common queries
    __table_args__ = (
        Index("ix_agents_org", "organization_id"),
        Index("ix_agents_workspace", "workspace_id"),
    )

    def __repr__(self) -> str:
        return f"<Agent {self.name} (model={self.model})>"


class CrewModel(Base):
    """Persisted crew definitions for SaaS users.

    Stores agents and tasks as JSON blobs and delegates execution to
    `ansiq.core.crew.Crew` at runtime.
    """

    __tablename__ = "crews"

    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    agents: Mapped[list] = mapped_column(JSON, default=list)
    tasks: Mapped[list] = mapped_column(JSON, default=list)
    process: Mapped[str] = mapped_column(String(32), default="pipeline")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))

    # Relationships
    organization: Mapped[Organization] = relationship(back_populates="crews")

    __table_args__ = (
        Index("ix_crews_org", "organization_id"),
    )

    def __repr__(self) -> str:
        return f"<Crew {self.name} (process={self.process})>"


class TaskModel(Base):
    """Persisted task definitions for SaaS users."""

    __tablename__ = "tasks"

    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("workspaces.id"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    expected_output: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))

    __table_args__ = (
        Index("ix_tasks_org", "organization_id"),
    )

    def __repr__(self) -> str:
        return f"<Task {self.name}>"


# ══════════════════════════════════════════════════════════════════════════
# User & Auth
# ══════════════════════════════════════════════════════════════════════════


class User(Base):
    """SaaS user account."""

    __tablename__ = "users"

    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    # password_hash stores the bcrypt PHC string (~60 chars). 255 gives
    # us headroom for future migrations to argon2 (≈ 95 chars).
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.MEMBER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    preferences: Mapped[dict | None] = mapped_column(JSON, default=dict)
    # MFA / TOTP (encrypted at rest via saas.crypto when set).
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_secret: Mapped[str | None] = mapped_column(String(512))
    # GDPR: soft-delete support. Hard-delete is a separate scheduled job.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deletion_scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    organization: Mapped[Organization] = relationship(back_populates="users")
    sessions: Mapped[list[Session]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    api_keys: Mapped[list[ApiKey]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    email_tokens: Mapped[list[EmailVerificationToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    password_reset_tokens: Mapped[list[PasswordResetToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role.value})>"


class Session(Base):
    """Active user session (JWT refresh token tracking)."""

    __tablename__ = "sessions"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    refresh_token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    user: Mapped[User] = relationship(back_populates="sessions")

    __table_args__ = (Index("ix_sessions_expires", "expires_at"),)


class ApiKey(Base):
    """API key for programmatic access."""

    __tablename__ = "api_keys"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    scope: Mapped[ApiKeyScope] = mapped_column(Enum(ApiKeyScope), default=ApiKeyScope.READ)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=60)
    allowed_ips: Mapped[list | None] = mapped_column(JSON, default=list)

    # Relationships
    user: Mapped[User] = relationship(back_populates="api_keys")

    def __repr__(self) -> str:
        return f"<ApiKey {self.name} ({self.key_prefix}...)>"


class EmailVerificationToken(Base):
    """Single-use email-verification token. Created on signup, consumed
    when the user clicks the link in the verification email.
    """

    __tablename__ = "email_verification_tokens"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    user: Mapped[User] = relationship(back_populates="email_tokens")

    @staticmethod
    def new_token() -> tuple[str, str]:
        """Return (raw_token, sha256_hash). Only the hash is persisted."""
        raw = secrets.token_urlsafe(32)
        import hashlib

        return raw, hashlib.sha256(raw.encode()).hexdigest()

    def is_expired(self) -> bool:
        return datetime.now(UTC) > self.expires_at

    def is_valid(self) -> bool:
        return not self.is_used and not self.is_expired()


class PasswordResetToken(Base):
    """Single-use password-reset token. Created when a user requests a
    reset, consumed when they submit a new password with the token.
    """

    __tablename__ = "password_reset_tokens"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    ip_address: Mapped[str | None] = mapped_column(String(45))

    user: Mapped[User] = relationship(back_populates="password_reset_tokens")

    @staticmethod
    def new_token() -> tuple[str, str]:
        """Return (raw_token, sha256_hash). Only the hash is persisted."""
        raw = secrets.token_urlsafe(32)
        import hashlib

        return raw, hashlib.sha256(raw.encode()).hexdigest()

    def is_expired(self) -> bool:
        return datetime.now(UTC) > self.expires_at

    def is_valid(self) -> bool:
        return not self.is_used and not self.is_expired()


# ══════════════════════════════════════════════════════════════════════════
# Subscription & Billing
# ══════════════════════════════════════════════════════════════════════════


class Subscription(Base):
    """Stripe subscription linked to an organization."""

    __tablename__ = "subscriptions"

    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    stripe_subscription_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    stripe_customer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    stripe_price_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus), default=SubscriptionStatus.TRIALING
    )
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    trial_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trial_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    plan: Mapped[OrgPlan] = mapped_column(Enum(OrgPlan), default=OrgPlan.FREE)
    # Renamed from "meta" (reserved word in some SQL dialects) to a
    # Python attribute "extra_metadata" mapped to the column
    # "subscription_metadata" for forward compatibility.
    extra_metadata: Mapped[dict | None] = mapped_column("subscription_metadata", JSON, default=dict)

    # Relationships
    organization: Mapped[Organization] = relationship(back_populates="subscriptions")
    invoices: Mapped[list[Invoice]] = relationship(
        back_populates="subscription", cascade="all, delete-orphan"
    )

    def is_active(self) -> bool:
        return self.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING)

    def __repr__(self) -> str:
        return f"<Subscription {self.stripe_subscription_id} ({self.status.value})>"


class Invoice(Base):
    """Billing invoice record."""

    __tablename__ = "invoices"

    subscription_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subscriptions.id"), nullable=False, index=True
    )
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    stripe_invoice_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    amount_due: Mapped[int] = mapped_column(Integer, nullable=False)  # cents
    amount_paid: Mapped[int | None] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="usd")
    status: Mapped[InvoiceStatus] = mapped_column(Enum(InvoiceStatus), default=InvoiceStatus.DRAFT)
    invoice_pdf_url: Mapped[str | None] = mapped_column(String(500))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lines: Mapped[list | None] = mapped_column(JSON, default=list)

    # Relationships
    subscription: Mapped[Subscription] = relationship(back_populates="invoices")

    def __repr__(self) -> str:
        return f"<Invoice {self.stripe_invoice_id} (${self.amount_due / 100:.2f})>"


class UsageRecord(Base):
    """Metered usage for billing."""

    __tablename__ = "usage_records"

    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("workspaces.id"))
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    metric: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        Index("ix_usage_org_metric_date", "organization_id", "metric", "recorded_at"),
    )

    def __repr__(self) -> str:
        return f"<UsageRecord {self.metric}: {self.quantity}>"


# ══════════════════════════════════════════════════════════════════════════
# Webhooks
# ══════════════════════════════════════════════════════════════════════════


class WebhookEndpoint(Base):
    """Registered webhook endpoint for an organization."""

    __tablename__ = "webhook_endpoints"

    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    # Secret used to sign payloads. In production this should be
    # encrypted at rest (KMS / pgcrypto). Stored as opaque text here.
    secret: Mapped[str] = mapped_column(String(255), nullable=False)
    events: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(String(500))
    headers: Mapped[dict | None] = mapped_column(JSON, default=dict)
    retry_count: Mapped[int] = mapped_column(Integer, default=3)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=10)

    # Relationships
    events_log: Mapped[list[WebhookEvent]] = relationship(
        back_populates="endpoint", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<WebhookEndpoint {self.url}>"


class WebhookEvent(Base):
    """Delivered webhook event."""

    __tablename__ = "webhook_events"

    endpoint_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("webhook_endpoints.id"), nullable=False, index=True
    )
    event_type: Mapped[WebhookEventType] = mapped_column(Enum(WebhookEventType), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_response_code: Mapped[int | None] = mapped_column(Integer)
    last_response_body: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    endpoint: Mapped[WebhookEndpoint] = relationship(back_populates="events_log")

    __table_args__ = (Index("ix_webhook_events_status", "status", "created_at"),)


# ══════════════════════════════════════════════════════════════════════════
# Audit Log
# ══════════════════════════════════════════════════════════════════════════


class AuditLog(Base):
    """Immutable audit trail for all SaaS operations."""

    __tablename__ = "audit_logs"

    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(36))
    details: Mapped[dict | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    severity: Mapped[str] = mapped_column(String(20), default="info")

    __table_args__ = (
        Index("ix_audit_logs_org_action", "organization_id", "action", "created_at"),
        Index("ix_audit_logs_org_date", "organization_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} on {self.resource_type}/{self.resource_id}>"

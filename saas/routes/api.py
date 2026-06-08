"""Main SaaS API surface — workspaces, API keys, agents, crews, tasks,
billing, webhooks, usage, members.

Every endpoint is tenant-scoped (always filtered by ``organization_id``)
and requires an authenticated user via :func:`get_current_user`.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from saas.auth import (
    get_current_user,
    hash_password,
)
from saas.billing import billing_service
from saas.database import get_db
from saas.models import (
    ApiKey,
    ApiKeyScope,
    Invoice,
    Organization,
    Subscription,
    UsageRecord,
    User,
    UserRole,
    WebhookEndpoint,
    WebhookEvent,
    WebhookEventType,
    Workspace,
)
from saas.webhooks import dispatch_webhook

logger = logging.getLogger("ansiq.saas.api")

router = APIRouter(prefix="/api/v1", tags=["API"])


# ── Helpers ─────────────────────────────────────────────────────────────


def _require_org(user: User) -> str:
    if not user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has no organization",
        )
    return user.organization_id


def _require_admin(user: User) -> None:
    if user.role not in (UserRole.OWNER, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )


# ═══════════════════════════════════════════════════════════════════════
# Workspaces
# ═══════════════════════════════════════════════════════════════════════


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class WorkspaceOut(BaseModel):
    id: str
    name: str
    slug: str
    description: str | None
    is_archived: bool
    created_at: str
    organization_id: str

    model_config = {"from_attributes": True}


@router.get("/workspaces", response_model=list[WorkspaceOut])
async def list_workspaces(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = _require_org(user)
    result = await db.execute(
        select(Workspace)
        .where(
            Workspace.organization_id == org_id,
            Workspace.is_archived == False,  # noqa: E712
        )
        .order_by(Workspace.created_at.desc())
    )
    items = result.scalars().all()
    return [
        WorkspaceOut(
            id=w.id,
            name=w.name,
            slug=w.slug,
            description=w.description,
            is_archived=w.is_archived,
            created_at=w.created_at.isoformat(),
            organization_id=w.organization_id,
        )
        for w in items
    ]


@router.post(
    "/workspaces",
    response_model=WorkspaceOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace(
    req: WorkspaceCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = _require_org(user)

    # Plan-limit enforcement: count existing non-archived workspaces.
    count = await db.execute(
        select(func.count(Workspace.id)).where(
            Workspace.organization_id == org_id,
            Workspace.is_archived == False,  # noqa: E712
        )
    )
    org = await db.get(Organization, org_id)
    if org and count.scalar() >= org.max_workspaces:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Workspace limit ({org.max_workspaces}) reached. Upgrade your plan.",
        )

    slug = "-".join(req.name.lower().split())[:90] + "-" + secrets.token_hex(3)

    ws = Workspace(
        organization_id=org_id,
        name=req.name,
        slug=slug,
        description=req.description,
        settings=req.settings,
    )
    db.add(ws)
    await db.flush()
    await db.refresh(ws)
    return WorkspaceOut(
        id=ws.id,
        name=ws.name,
        slug=ws.slug,
        description=ws.description,
        is_archived=ws.is_archived,
        created_at=ws.created_at.isoformat(),
        organization_id=ws.organization_id,
    )


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(
    workspace_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = _require_org(user)
    ws = await db.get(Workspace, workspace_id)
    if not ws or ws.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return WorkspaceOut(
        id=ws.id,
        name=ws.name,
        slug=ws.slug,
        description=ws.description,
        is_archived=ws.is_archived,
        created_at=ws.created_at.isoformat(),
        organization_id=ws.organization_id,
    )


@router.delete("/workspaces/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_workspace(
    workspace_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = _require_org(user)
    _require_admin(user)
    ws = await db.get(Workspace, workspace_id)
    if not ws or ws.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Workspace not found")
    ws.is_archived = True
    await db.flush()


# ═══════════════════════════════════════════════════════════════════════
# API Keys
# ═══════════════════════════════════════════════════════════════════════


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    scope: ApiKeyScope = ApiKeyScope.READ
    expires_in_days: int | None = Field(default=None, ge=1, le=365)
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10000)


class ApiKeyCreated(BaseModel):
    id: str
    name: str
    key_prefix: str
    scope: str
    expires_at: str | None
    created_at: str
    # Returned ONLY on creation.
    secret: str


class ApiKeyOut(BaseModel):
    id: str
    name: str
    key_prefix: str
    scope: str
    expires_at: str | None
    last_used_at: str | None
    is_active: bool
    rate_limit_per_minute: int
    created_at: str


@router.get("/api-keys", response_model=list[ApiKeyOut])
async def list_api_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = _require_org(user)
    result = await db.execute(
        select(ApiKey, User)
        .join(User, User.id == ApiKey.user_id)
        .where(
            User.organization_id == org_id,
            ApiKey.is_active == True,  # noqa: E712
        )
        .order_by(ApiKey.created_at.desc())
    )
    out = []
    for key, _u in result.all():
        out.append(
            ApiKeyOut(
                id=key.id,
                name=key.name,
                key_prefix=key.key_prefix,
                scope=key.scope.value,
                expires_at=(key.expires_at.isoformat() if key.expires_at else None),
                last_used_at=(key.last_used_at.isoformat() if key.last_used_at else None),
                is_active=key.is_active,
                rate_limit_per_minute=key.rate_limit_per_minute,
                created_at=key.created_at.isoformat(),
            )
        )
    return out


@router.post(
    "/api-keys",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    req: ApiKeyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a new API key. The raw secret is returned ONLY here —
    it cannot be retrieved later.
    """
    raw = f"ansiq_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    expires_at = None
    if req.expires_in_days:
        from datetime import timedelta

        expires_at = datetime.now(UTC) + timedelta(days=req.expires_in_days)
    key = ApiKey(
        user_id=user.id,
        name=req.name,
        key_prefix=raw[:16] + "...",
        key_hash=key_hash,
        scope=req.scope,
        expires_at=expires_at,
        rate_limit_per_minute=req.rate_limit_per_minute,
    )
    db.add(key)
    await db.flush()
    await db.refresh(key)
    return ApiKeyCreated(
        id=key.id,
        name=key.name,
        key_prefix=key.key_prefix,
        scope=key.scope.value,
        expires_at=key.expires_at.isoformat() if key.expires_at else None,
        created_at=key.created_at.isoformat(),
        secret=raw,
    )


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = _require_org(user)
    result = await db.execute(
        select(ApiKey, User)
        .join(User, User.id == ApiKey.user_id)
        .where(
            ApiKey.id == key_id,
            User.organization_id == org_id,
        )
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="API key not found")
    key, _u = row
    key.is_active = False
    await db.flush()


# ═══════════════════════════════════════════════════════════════════════
# Members (users within an organization)
# ═══════════════════════════════════════════════════════════════════════


class MemberOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    is_verified: bool
    last_login_at: str | None
    created_at: str


class MemberInvite(BaseModel):
    email: str
    full_name: str
    password: str = Field(..., min_length=8, max_length=128)
    role: UserRole = UserRole.MEMBER


class MemberRoleUpdate(BaseModel):
    role: UserRole


@router.get("/members", response_model=list[MemberOut])
async def list_members(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = _require_org(user)
    result = await db.execute(
        select(User).where(User.organization_id == org_id).order_by(User.created_at)
    )
    return [
        MemberOut(
            id=u.id,
            email=u.email,
            full_name=u.full_name,
            role=u.role.value,
            is_active=u.is_active,
            is_verified=u.is_verified,
            last_login_at=(u.last_login_at.isoformat() if u.last_login_at else None),
            created_at=u.created_at.isoformat(),
        )
        for u in result.scalars()
    ]


@router.post(
    "/members",
    response_model=MemberOut,
    status_code=status.HTTP_201_CREATED,
)
async def invite_member(
    req: MemberInvite,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = _require_org(user)
    _require_admin(user)

    # Plan-limit enforcement.
    count = await db.execute(
        select(func.count(User.id)).where(
            User.organization_id == org_id,
            User.is_active == True,  # noqa: E712
        )
    )
    org = await db.get(Organization, org_id)
    if org and count.scalar() >= org.max_users:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"User limit ({org.max_users}) reached.",
        )

    email_norm = req.email.strip().lower()
    existing = await db.execute(select(User).where(User.email == email_norm))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    new_user = User(
        email=email_norm,
        password_hash=hash_password(req.password),
        full_name=req.full_name,
        organization_id=org_id,
        role=req.role,
        is_verified=True,  # admin-added users are pre-verified
    )
    db.add(new_user)
    await db.flush()
    await db.refresh(new_user)
    return MemberOut(
        id=new_user.id,
        email=new_user.email,
        full_name=new_user.full_name,
        role=new_user.role.value,
        is_active=new_user.is_active,
        is_verified=new_user.is_verified,
        last_login_at=None,
        created_at=new_user.created_at.isoformat(),
    )


@router.patch("/members/{member_id}/role", response_model=MemberOut)
async def update_member_role(
    member_id: str,
    req: MemberRoleUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = _require_org(user)
    _require_admin(user)
    member = await db.get(User, member_id)
    if not member or member.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Member not found")
    member.role = req.role
    await db.flush()
    return MemberOut(
        id=member.id,
        email=member.email,
        full_name=member.full_name,
        role=member.role.value,
        is_active=member.is_active,
        is_verified=member.is_verified,
        last_login_at=(member.last_login_at.isoformat() if member.last_login_at else None),
        created_at=member.created_at.isoformat(),
    )


@router.delete("/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_member(
    member_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = _require_org(user)
    _require_admin(user)
    if member_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate yourself",
        )
    member = await db.get(User, member_id)
    if not member or member.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Member not found")
    member.is_active = False
    await db.flush()


# ═══════════════════════════════════════════════════════════════════════
# Webhooks
# ═══════════════════════════════════════════════════════════════════════


class WebhookCreate(BaseModel):
    url: str = Field(..., min_length=8, max_length=500)
    events: list[str] = Field(default_factory=list)
    description: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    retry_count: int = Field(default=3, ge=0, le=10)
    timeout_seconds: int = Field(default=10, ge=1, le=60)


class WebhookOut(BaseModel):
    id: str
    url: str
    events: list
    is_active: bool
    description: str | None
    retry_count: int
    timeout_seconds: int
    created_at: str
    secret: str  # Shown on creation only; encrypted at rest in production.


@router.get("/webhooks", response_model=list[WebhookOut])
async def list_webhooks(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = _require_org(user)
    result = await db.execute(
        select(WebhookEndpoint)
        .where(WebhookEndpoint.organization_id == org_id)
        .order_by(WebhookEndpoint.id)
    )
    return [
        WebhookOut(
            id=e.id,
            url=e.url,
            events=e.events,
            is_active=e.is_active,
            description=e.description,
            retry_count=e.retry_count,
            timeout_seconds=e.timeout_seconds,
            created_at=e.created_at.isoformat(),
            secret=e.secret,  # NB: in production, never return secret
        )
        for e in result.scalars()
    ]


@router.post(
    "/webhooks",
    response_model=WebhookOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_webhook(
    req: WebhookCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = _require_org(user)
    _require_admin(user)
    # Validate that all event types are known.
    valid = {e.value for e in WebhookEventType}
    for ev in req.events:
        if ev != "*" and ev not in valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown event type: {ev}",
            )
    secret = secrets.token_urlsafe(32)
    from saas.crypto import encrypt as _encrypt_secret

    ep = WebhookEndpoint(
        organization_id=org_id,
        url=req.url,
        secret=_encrypt_secret(secret),  # Encrypted at rest.
        events=req.events,
        is_active=True,
        description=req.description,
        headers=req.headers,
        retry_count=req.retry_count,
        timeout_seconds=req.timeout_seconds,
    )
    db.add(ep)
    await db.flush()
    await db.refresh(ep)
    return WebhookOut(
        id=ep.id,
        url=ep.url,
        events=ep.events,
        is_active=ep.is_active,
        description=ep.description,
        retry_count=ep.retry_count,
        timeout_seconds=ep.timeout_seconds,
        created_at=ep.created_at.isoformat(),
        secret=secret,
    )


@router.delete("/webhooks/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    endpoint_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = _require_org(user)
    _require_admin(user)
    ep = await db.get(WebhookEndpoint, endpoint_id)
    if not ep or ep.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Webhook not found")
    ep.is_active = False
    await db.flush()


@router.get("/webhooks/events", response_model=list[str])
async def list_webhook_event_types(
    user: User = Depends(get_current_user),
):
    return [e.value for e in WebhookEventType]


# ═══════════════════════════════════════════════════════════════════════
# Organization / Tenant
# ═══════════════════════════════════════════════════════════════════════


class OrganizationOut(BaseModel):
    id: str
    name: str
    slug: str
    plan: str
    is_active: bool
    max_users: int
    max_workspaces: int
    max_tasks_per_month: int
    trial_ends_at: str | None
    billing_email: str | None = None
    created_at: str


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    billing_email: str | None = None


@router.get("/organization", response_model=OrganizationOut)
async def get_organization(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = _require_org(user)
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return OrganizationOut(
        id=org.id,
        name=org.name,
        slug=org.slug,
        plan=org.plan.value,
        is_active=org.is_active,
        max_users=org.max_users,
        max_workspaces=org.max_workspaces,
        max_tasks_per_month=org.max_tasks_per_month,
        trial_ends_at=(org.trial_ends_at.isoformat() if org.trial_ends_at else None),
        billing_email=org.billing_email,
        created_at=org.created_at.isoformat(),
    )


@router.patch("/organization", response_model=OrganizationOut)
async def update_organization(
    req: OrganizationUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = _require_org(user)
    _require_admin(user)
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    if req.name:
        org.name = req.name
    if req.billing_email:
        org.billing_email = req.billing_email
    await db.flush()
    return OrganizationOut(
        id=org.id,
        name=org.name,
        slug=org.slug,
        plan=org.plan.value,
        is_active=org.is_active,
        max_users=org.max_users,
        max_workspaces=org.max_workspaces,
        max_tasks_per_month=org.max_tasks_per_month,
        trial_ends_at=(org.trial_ends_at.isoformat() if org.trial_ends_at else None),
        billing_email=org.billing_email,
        created_at=org.created_at.isoformat(),
    )


# ═══════════════════════════════════════════════════════════════════════
# Billing — Subscriptions & Invoices
# ═══════════════════════════════════════════════════════════════════════


class SubscriptionOut(BaseModel):
    id: str
    stripe_subscription_id: str
    status: str
    plan: str
    current_period_start: str | None
    current_period_end: str | None
    cancel_at_period_end: bool
    trial_start: str | None
    trial_end: str | None


class InvoiceOut(BaseModel):
    id: str
    stripe_invoice_id: str
    amount_due: int
    amount_paid: int
    currency: str
    status: str
    invoice_pdf_url: str | None
    period_start: str | None
    period_end: str | None
    paid_at: str | None


class CheckoutRequest(BaseModel):
    price_id: str
    trial_days: int = Field(default=14, ge=0, le=60)


@router.get("/billing/subscription", response_model=SubscriptionOut | None)
async def get_subscription(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = _require_org(user)
    result = await db.execute(
        select(Subscription)
        .where(Subscription.organization_id == org_id)
        .order_by(Subscription.id.desc())
        .limit(1)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        return None
    return SubscriptionOut(
        id=sub.id,
        stripe_subscription_id=sub.stripe_subscription_id,
        status=sub.status.value,
        plan=sub.plan.value,
        current_period_start=(
            sub.current_period_start.isoformat() if sub.current_period_start else None
        ),
        current_period_end=(sub.current_period_end.isoformat() if sub.current_period_end else None),
        cancel_at_period_end=sub.cancel_at_period_end,
        trial_start=(sub.trial_start.isoformat() if sub.trial_start else None),
        trial_end=(sub.trial_end.isoformat() if sub.trial_end else None),
    )


@router.post(
    "/billing/checkout",
    response_model=SubscriptionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_checkout(
    req: CheckoutRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe Checkout subscription for the current org."""
    org_id = _require_org(user)
    _require_admin(user)
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Ensure the org has a Stripe customer.
    if not org.stripe_customer_id:
        try:
            await billing_service.create_customer(
                org,
                email=org.billing_email or user.email,
                name=org.name,
            )
            await db.flush()
        except Exception as exc:
            logger.exception("Stripe customer creation failed")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Billing provider error: {type(exc).__name__}",
            )

    try:
        sub = await billing_service.create_subscription(
            org,
            price_id=req.price_id,
            trial_days=req.trial_days,
        )
    except Exception as exc:
        logger.exception("Stripe subscription creation failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Billing provider error: {type(exc).__name__}",
        )

    db.add(sub)
    await db.flush()
    return SubscriptionOut(
        id=sub.id,
        stripe_subscription_id=sub.stripe_subscription_id,
        status=sub.status.value,
        plan=sub.plan.value,
        current_period_start=(
            sub.current_period_start.isoformat() if sub.current_period_start else None
        ),
        current_period_end=(sub.current_period_end.isoformat() if sub.current_period_end else None),
        cancel_at_period_end=sub.cancel_at_period_end,
        trial_start=(sub.trial_start.isoformat() if sub.trial_start else None),
        trial_end=(sub.trial_end.isoformat() if sub.trial_end else None),
    )


@router.post("/billing/cancel", status_code=status.HTTP_200_OK)
async def cancel_subscription(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = _require_org(user)
    _require_admin(user)
    result = await db.execute(
        select(Subscription)
        .where(Subscription.organization_id == org_id)
        .order_by(Subscription.id.desc())
        .limit(1)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="No active subscription")
    try:
        await billing_service.cancel_subscription(
            sub.stripe_subscription_id,
            at_period_end=True,
        )
    except Exception as exc:
        logger.exception("Stripe subscription cancel failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Billing provider error: {type(exc).__name__}",
        )
    sub.cancel_at_period_end = True
    await db.flush()
    return {"status": "cancelled_at_period_end"}


@router.get("/billing/invoices", response_model=list[InvoiceOut])
async def list_invoices(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = _require_org(user)
    result = await db.execute(
        select(Invoice)
        .where(Invoice.organization_id == org_id)
        .order_by(Invoice.id.desc())
        .limit(100)
    )
    return [
        InvoiceOut(
            id=i.id,
            stripe_invoice_id=i.stripe_invoice_id,
            amount_due=i.amount_due,
            amount_paid=i.amount_paid or 0,
            currency=i.currency,
            status=i.status.value,
            invoice_pdf_url=i.invoice_pdf_url,
            period_start=(i.period_start.isoformat() if i.period_start else None),
            period_end=(i.period_end.isoformat() if i.period_end else None),
            paid_at=(i.paid_at.isoformat() if i.paid_at else None),
        )
        for i in result.scalars()
    ]


# ═══════════════════════════════════════════════════════════════════════
# Usage / Analytics
# ═══════════════════════════════════════════════════════════════════════


class UsageRecordIn(BaseModel):
    metric: str = Field(..., min_length=1, max_length=100)
    quantity: int = Field(default=1, ge=1)
    workspace_id: str | None = None


class UsageRecordOut(BaseModel):
    id: str
    metric: str
    quantity: int
    workspace_id: str | None
    recorded_at: str


@router.post(
    "/usage",
    response_model=UsageRecordOut,
    status_code=status.HTTP_201_CREATED,
)
async def record_usage(
    req: UsageRecordIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = _require_org(user)
    rec = UsageRecord(
        organization_id=org_id,
        workspace_id=req.workspace_id,
        user_id=user.id,
        metric=req.metric,
        quantity=req.quantity,
    )
    db.add(rec)
    await db.flush()
    await db.refresh(rec)
    return UsageRecordOut(
        id=rec.id,
        metric=rec.metric,
        quantity=rec.quantity,
        workspace_id=rec.workspace_id,
        recorded_at=rec.recorded_at.isoformat(),
    )


@router.get("/usage", response_model=list[UsageRecordOut])
async def list_usage(
    metric: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from datetime import timedelta

    org_id = _require_org(user)
    since = datetime.now(UTC) - timedelta(days=days)
    stmt = select(UsageRecord).where(
        UsageRecord.organization_id == org_id,
        UsageRecord.recorded_at >= since,
    )
    if metric:
        stmt = stmt.where(UsageRecord.metric == metric)
    stmt = stmt.order_by(UsageRecord.recorded_at.desc()).limit(1000)
    result = await db.execute(stmt)
    return [
        UsageRecordOut(
            id=r.id,
            metric=r.metric,
            quantity=r.quantity,
            workspace_id=r.workspace_id,
            recorded_at=r.recorded_at.isoformat(),
        )
        for r in result.scalars()
    ]


# ═══════════════════════════════════════════════════════════════════════
# Agent / Crew / Task execution
#
# These endpoints accept a high-level task and delegate to the underlying
# ansiq orchestration framework. They are kept thin on purpose — the real
# value of AnsiQ lives in the framework, not the API.
# ═══════════════════════════════════════════════════════════════════════


class AgentRunRequest(BaseModel):
    task: str = Field(..., min_length=1, max_length=10_000)
    model: str | None = None
    context: str | None = None
    workspace_id: str | None = None


class AgentRunResponse(BaseModel):
    output: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0


@router.post(
    "/agents/run",
    response_model=AgentRunResponse,
)
async def run_agent(
    req: AgentRunRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run a single agent against the supplied task.

    This is a thin wrapper around the ansiq orchestration framework.
    The framework selects a model via the LLM router and tracks
    token / cost usage which is recorded to the UsageRecord table.
    """
    org_id = _require_org(user)
    import time as _time

    from ansiq.core.agent import Agent
    from ansiq.core.identity import AgentIdentity

    try:
        agent = Agent(
            identity=AgentIdentity(
                name=f"{user.full_name}'s Agent",
                role="assistant",
                goal="Help the user accomplish their task accurately.",
            ),
            model=req.model,
        )
        start = _time.time()
        response = await agent.run(task=req.task, context=req.context)
        duration_ms = int((_time.time() - start) * 1000)
        content = response.content if hasattr(response, "content") else str(response)
        prompt_tokens = getattr(response, "prompt_tokens", 0) or 0
        completion_tokens = getattr(response, "completion_tokens", 0) or 0
        cost = getattr(response, "cost_usd", 0.0) or 0.0
        model = getattr(response, "model", None) or (req.model or "default")
    except Exception as exc:
        logger.exception("Agent run failed for org %s", org_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent execution failed: {type(exc).__name__}",
        )

    # Record usage.
    db.add(
        UsageRecord(
            organization_id=org_id,
            workspace_id=req.workspace_id,
            user_id=user.id,
            metric="agent_run",
            quantity=1,
        )
    )
    db.add(
        UsageRecord(
            organization_id=org_id,
            workspace_id=req.workspace_id,
            user_id=user.id,
            metric="tokens",
            quantity=prompt_tokens + completion_tokens,
        )
    )
    await db.flush()

    # Fire-and-forget webhook for downstream consumers.
    try:
        await dispatch_webhook(
            org_id=org_id,
            event_type=WebhookEventType.AGENT_COMPLETED,
            payload={
                "user_id": user.id,
                "task_preview": req.task[:200],
                "model": model,
                "duration_ms": duration_ms,
            },
            db=db,
        )
    except Exception:
        logger.exception("Failed to dispatch agent.completed webhook")

    return AgentRunResponse(
        output=content,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost,
        duration_ms=duration_ms,
    )


# ═══════════════════════════════════════════════════════════════════════
# Audit Log (read-only)
# ═══════════════════════════════════════════════════════════════════════


class AuditLogOut(BaseModel):
    id: str
    action: str
    resource_type: str
    resource_id: str | None
    severity: str
    details: dict | None
    ip_address: str | None
    user_id: str | None
    created_at: str


@router.get("/audit-logs", response_model=list[AuditLogOut])
async def list_audit_logs(
    action: str | None = None,
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=100, ge=1, le=1000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = _require_org(user)
    _require_admin(user)
    from datetime import timedelta

    from saas.models import AuditLog

    since = datetime.now(UTC) - timedelta(days=days)
    stmt = select(AuditLog).where(
        AuditLog.organization_id == org_id,
        AuditLog.created_at >= since,
    )
    if action:
        stmt = stmt.where(AuditLog.action == action)
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return [
        AuditLogOut(
            id=audit_log.id,
            action=audit_log.action,
            resource_type=audit_log.resource_type,
            resource_id=audit_log.resource_id,
            severity=audit_log.severity,
            details=audit_log.details,
            ip_address=audit_log.ip_address,
            user_id=audit_log.user_id,
            created_at=audit_log.created_at.isoformat(),
        )
        for audit_log in result.scalars()
    ]


# ═══════════════════════════════════════════════════════════════════════
# Webhook event log (read-only)
# ═══════════════════════════════════════════════════════════════════════


class WebhookEventOut(BaseModel):
    id: str
    endpoint_id: str
    event_type: str
    status: str
    attempt_count: int
    last_response_code: int | None
    delivered_at: str | None
    created_at: str


@router.get(
    "/webhooks/{endpoint_id}/events",
    response_model=list[WebhookEventOut],
)
async def list_webhook_events(
    endpoint_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = _require_org(user)
    ep = await db.get(WebhookEndpoint, endpoint_id)
    if not ep or ep.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Webhook not found")
    result = await db.execute(
        select(WebhookEvent)
        .where(
            WebhookEvent.endpoint_id == endpoint_id,
        )
        .order_by(WebhookEvent.created_at.desc())
        .limit(limit)
    )
    return [
        WebhookEventOut(
            id=e.id,
            endpoint_id=e.endpoint_id,
            event_type=e.event_type.value,
            status=e.status,
            attempt_count=e.attempt_count,
            last_response_code=e.last_response_code,
            delivered_at=(e.delivered_at.isoformat() if e.delivered_at else None),
            created_at=e.created_at.isoformat(),
        )
        for e in result.scalars()
    ]


# ═══════════════════════════════════════════════════════════════════════
# Health of the tenant
# ═══════════════════════════════════════════════════════════════════════


class HealthOut(BaseModel):
    status: str
    organization: str
    plan: str
    workspaces: int
    members: int
    api_keys: int
    webhooks: int
    subscription: str | None


@router.get("/health", response_model=HealthOut)
async def tenant_health(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = _require_org(user)
    org = await db.get(Organization, org_id)

    ws_count = await db.execute(
        select(func.count(Workspace.id)).where(
            Workspace.organization_id == org_id,
            Workspace.is_archived == False,  # noqa: E712
        )
    )
    member_count = await db.execute(
        select(func.count(User.id)).where(
            User.organization_id == org_id,
            User.is_active == True,  # noqa: E712
        )
    )
    key_count = await db.execute(
        select(func.count(ApiKey.id)).where(
            ApiKey.user_id.in_(
                select(User.id).where(User.organization_id == org_id).scalar_subquery()
            ),
            ApiKey.is_active == True,  # noqa: E712
        )
    )
    hook_count = await db.execute(
        select(func.count(WebhookEndpoint.id)).where(
            WebhookEndpoint.organization_id == org_id,
            WebhookEndpoint.is_active == True,  # noqa: E712
        )
    )
    sub_result = await db.execute(
        select(Subscription)
        .where(Subscription.organization_id == org_id)
        .order_by(Subscription.id.desc())
        .limit(1)
    )
    sub = sub_result.scalar_one_or_none()

    return HealthOut(
        status="ok",
        organization=org.name if org else "?",
        plan=org.plan.value if org else "free",
        workspaces=ws_count.scalar() or 0,
        members=member_count.scalar() or 0,
        api_keys=key_count.scalar() or 0,
        webhooks=hook_count.scalar() or 0,
        subscription=sub.status.value if sub else None,
    )

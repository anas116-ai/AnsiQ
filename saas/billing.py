"""Stripe billing integration — subscriptions, invoices, metering."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import stripe
from sqlalchemy import select

from saas.config import config
from saas.database import AsyncSessionLocal
from saas.models import (
    Invoice,
    InvoiceStatus,
    Organization,
    OrgPlan,
    Subscription,
    SubscriptionStatus,
)

logger = logging.getLogger("ansiq.saas.billing")

# Only configure Stripe if a real key is provided. Without a key, the Stripe
# SDK still works for some read-only operations but will fail on write — this
# avoids hard-import crashes when billing is disabled in dev/test.
if config.stripe.secret_key:
    stripe.api_key = config.stripe.secret_key


def _to_utc_dt(value: Any) -> datetime | None:
    """Safely convert a Stripe epoch int to a tz-aware datetime."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _to_subscription_status(value: Any) -> SubscriptionStatus:
    """Convert a Stripe status string to our enum, falling back to
    TRIALING for unknown values so a new Stripe status never crashes
    the webhook handler.
    """
    try:
        return SubscriptionStatus(value)
    except ValueError:
        logger.warning("Unknown Stripe subscription status: %r", value)
        return SubscriptionStatus.TRIALING


def _to_invoice_status(value: Any) -> InvoiceStatus:
    try:
        return InvoiceStatus(value)
    except ValueError:
        logger.warning("Unknown Stripe invoice status: %r", value)
        return InvoiceStatus.OPEN


class BillingService:
    """Stripe-powered subscription & billing management."""

    async def create_customer(self, org: Organization, email: str, name: str) -> str:
        """Create a Stripe customer for an organization."""
        if not config.stripe.secret_key:
            raise RuntimeError("Stripe is not configured (STRIPE_SECRET_KEY missing)")
        customer = stripe.Customer.create(
            email=email,
            name=name,
            metadata={"org_id": org.id, "org_slug": org.slug},
        )
        org.stripe_customer_id = customer.id
        logger.info("Created Stripe customer %s for org %s", customer.id, org.slug)
        return customer.id

    async def create_subscription(
        self,
        org: Organization,
        price_id: str,
        trial_days: int = 14,
    ) -> Subscription:
        """Create a Stripe subscription and persist locally."""
        if not config.stripe.secret_key:
            raise RuntimeError("Stripe is not configured (STRIPE_SECRET_KEY missing)")
        if not org.stripe_customer_id:
            raise ValueError("Organization has no Stripe customer ID")

        stripe_sub = stripe.Subscription.create(
            customer=org.stripe_customer_id,
            items=[{"price": price_id}],
            trial_period_days=trial_days,
            metadata={"org_id": org.id},
            payment_behavior="default_incomplete",
            expand=["latest_invoice.payment_intent"],
        )

        # Determine plan from price
        plan_map = {
            config.stripe.monthly_price_id: OrgPlan.PRO,
            config.stripe.yearly_price_id: OrgPlan.PRO,
        }
        plan = plan_map.get(price_id, OrgPlan.STARTER)

        sub = Subscription(
            organization_id=org.id,
            stripe_subscription_id=stripe_sub.id,
            stripe_customer_id=org.stripe_customer_id,
            stripe_price_id=price_id,
            status=_to_subscription_status(stripe_sub.status),
            current_period_start=_to_utc_dt(stripe_sub.current_period_start),
            current_period_end=_to_utc_dt(stripe_sub.current_period_end),
            trial_start=_to_utc_dt(stripe_sub.trial_start),
            trial_end=_to_utc_dt(stripe_sub.trial_end),
            plan=plan,
        )

        # Update org plan
        org.plan = plan
        trial_end_dt = _to_utc_dt(stripe_sub.trial_end)
        if trial_end_dt:
            org.trial_ends_at = trial_end_dt

        logger.info(
            "Created subscription %s for org %s (plan=%s)",
            sub.id,
            org.slug,
            plan.value,
        )
        return sub

    async def cancel_subscription(self, subscription_id: str, at_period_end: bool = True) -> None:
        """Cancel a Stripe subscription."""
        if not config.stripe.secret_key:
            raise RuntimeError("Stripe is not configured")
        stripe.Subscription.modify(
            subscription_id,
            cancel_at_period_end=at_period_end,
        )
        logger.info(
            "Subscription %s will cancel at period end=%s",
            subscription_id,
            at_period_end,
        )

    async def update_subscription(self, subscription_id: str, new_price_id: str) -> None:
        """Upgrade/downgrade subscription to a new price.

        The Stripe SDK returns a `StripeObject` whose attributes can be
        accessed via dot-notation, but for items we may get either a dict
        (when the resource is loaded via the API directly) or a
        ListObject (when expanded). We handle both safely.
        """
        if not config.stripe.secret_key:
            raise RuntimeError("Stripe is not configured")
        stripe_sub = stripe.Subscription.retrieve(subscription_id)
        items_data = _extract_stripe_items(stripe_sub)
        if not items_data:
            raise ValueError(f"Subscription {subscription_id} has no items")
        first_item = items_data[0]
        item_id = (
            first_item.get("id")
            if isinstance(first_item, dict)
            else getattr(first_item, "id", None)
        )
        if not item_id:
            raise ValueError(f"Cannot determine item id for subscription {subscription_id}")
        stripe.Subscription.modify(
            subscription_id,
            items=[{"id": item_id, "price": new_price_id}],
            proration_behavior="always_invoice",
        )
        logger.info(
            "Subscription %s updated to price %s",
            subscription_id,
            new_price_id,
        )

    async def handle_webhook(self, payload: bytes, sig_header: str) -> dict:
        """Process Stripe webhook events safely.

        Every handler is wrapped in a try/except so a single bad event
        cannot crash the entire webhook worker.
        """
        if not config.stripe.webhook_secret:
            raise RuntimeError("Stripe webhook secret not configured")
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, config.stripe.webhook_secret
            )
        except (ValueError, stripe.error.SignatureVerificationError) as e:
            logger.error("Stripe webhook signature invalid: %s", e)
            raise

        handler = self._webhook_handlers.get(event["type"])
        if handler:
            try:
                await handler(event["data"]["object"])
                logger.info("Stripe webhook %s processed", event["type"])
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Stripe webhook %s handler failed: %s",
                    event["type"],
                    exc,
                )
                # Re-raise so Stripe retries the event
                raise
        else:
            logger.debug("Unhandled Stripe webhook type: %s", event["type"])

        return {"status": "ok"}

    _webhook_handlers: dict[str, Any] = {}

    @classmethod
    def _register(cls, event_type: str):
        def decorator(func):
            cls._webhook_handlers[event_type] = func
            return func

        return decorator


def _extract_stripe_items(stripe_sub: Any) -> list:
    """Robustly extract the items list from a Stripe subscription object.

    Handles both:
      - ``stripe_sub.items`` as a ListObject (typical)
      - ``stripe_sub.items`` as a dict with key "data" (when the parent
        was loaded via the API in a non-expanded form)
    """
    items = getattr(stripe_sub, "items", None)
    if items is None:
        return []
    if isinstance(items, dict):
        return items.get("data", []) or []
    data = getattr(items, "data", None)
    if data is not None:
        return list(data)
    return []


# ── Webhook Handlers ────────────────────────────────────────────────────


@BillingService._register("invoice.paid")
async def _on_invoice_paid(invoice: dict):
    async with AsyncSessionLocal() as db:
        try:
            db_invoice = await db.execute(
                select(Invoice).where(Invoice.stripe_invoice_id == invoice["id"])
            )
            db_invoice = db_invoice.scalar_one_or_none()
            if db_invoice:
                db_invoice.status = InvoiceStatus.PAID
                db_invoice.amount_paid = int(invoice.get("amount_paid", 0) or 0)
                db_invoice.paid_at = datetime.now(UTC)
                await db.commit()
                logger.info("Invoice %s marked as paid", invoice["id"])
        except Exception:
            await db.rollback()
            logger.exception("Failed to process invoice.paid for %s", invoice.get("id"))
            raise


@BillingService._register("invoice.payment_failed")
async def _on_invoice_failed(invoice: dict):
    async with AsyncSessionLocal() as db:
        try:
            db_invoice = await db.execute(
                select(Invoice).where(Invoice.stripe_invoice_id == invoice["id"])
            )
            db_invoice = db_invoice.scalar_one_or_none()
            if db_invoice:
                db_invoice.status = InvoiceStatus.UNCOLLECTIBLE
                await db.commit()
                logger.warning("Invoice %s payment failed", invoice["id"])
        except Exception:
            await db.rollback()
            logger.exception(
                "Failed to process invoice.payment_failed for %s",
                invoice.get("id"),
            )
            raise


@BillingService._register("customer.subscription.updated")
async def _on_subscription_updated(sub: dict):
    async with AsyncSessionLocal() as db:
        try:
            db_sub = await db.execute(
                select(Subscription).where(Subscription.stripe_subscription_id == sub["id"])
            )
            db_sub = db_sub.scalar_one_or_none()
            if db_sub:
                db_sub.status = _to_subscription_status(sub.get("status"))
                db_sub.current_period_start = _to_utc_dt(sub.get("current_period_start"))
                db_sub.current_period_end = _to_utc_dt(sub.get("current_period_end"))
                db_sub.cancel_at_period_end = bool(sub.get("cancel_at_period_end", False))
                await db.commit()
                logger.info(
                    "Subscription %s updated to %s",
                    sub["id"],
                    sub.get("status"),
                )
        except Exception:
            await db.rollback()
            logger.exception(
                "Failed to process customer.subscription.updated for %s",
                sub.get("id"),
            )
            raise


billing_service = BillingService()

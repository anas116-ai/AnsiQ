"""Webhook delivery system — dispatch, retry, sign.

Delivery is **asynchronous** and decoupled from the request thread:
``dispatch_webhook`` only persists ``WebhookEvent`` rows and schedules
delivery via ``asyncio.create_task``.  The originating HTTP request
returns immediately, so a slow customer endpoint cannot DoS the API.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from saas.database import AsyncSessionLocal
from saas.models import WebhookEndpoint, WebhookEvent, WebhookEventType

logger = logging.getLogger("ansiq.saas.webhooks")


# Limit on in-flight background delivery tasks so a sudden burst of
# webhooks doesn't blow up the event loop.
_MAX_INFLIGHT_DELIVERIES = 256
_delivery_semaphore = asyncio.Semaphore(_MAX_INFLIGHT_DELIVERIES)


def sign_payload(payload: bytes, secret: str) -> str:
    """HMAC-SHA256 signature for webhook payload (hex-encoded)."""
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


async def dispatch_webhook(
    org_id: str,
    event_type: WebhookEventType,
    payload: dict,
    db: AsyncSession | None = None,
) -> list[WebhookEvent]:
    """Persist webhook events and schedule background delivery.

    Returns immediately. Each persisted event is delivered in a
    background task with retries.
    """
    close_db = False
    if db is None:
        db = AsyncSessionLocal()
        close_db = True

    try:
        result = await db.execute(
            select(WebhookEndpoint).where(
                WebhookEndpoint.organization_id == org_id,
                WebhookEndpoint.is_active == True,  # noqa: E712
            )
        )
        endpoints = list(result.scalars().all())

        events: list[WebhookEvent] = []
        for ep in endpoints:
            if event_type.value not in ep.events and "*" not in ep.events:
                continue

            event = WebhookEvent(
                endpoint_id=ep.id,
                event_type=event_type,
                payload=payload,
                status="pending",
            )
            db.add(event)
            events.append(event)

        if close_db:
            await db.commit()
        else:
            await db.flush()
            for e in events:
                await db.refresh(e)
    finally:
        if close_db:
            await db.close()

    # Schedule background delivery — never block the request.
    for event in events:
        _schedule_delivery(event.id, event.endpoint_id, event.event_type, event.payload)

    return events


def _schedule_delivery(
    event_id: str,
    endpoint_id: str,
    event_type: WebhookEventType,
    payload: dict,
) -> None:
    """Schedule an async delivery task. Safe to call from sync code."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop (e.g., tests) — skip background delivery.
        logger.debug("No running loop; skipping background webhook delivery")
        return
    loop.create_task(_deliver(event_id, endpoint_id, event_type, payload))


async def _deliver(
    event_id: str,
    endpoint_id: str,
    event_type: WebhookEventType,
    payload: dict,
) -> None:
    """Deliver a single webhook event with retries (background task)."""
    async with _delivery_semaphore:
        async with AsyncSessionLocal() as db:
            try:
                result = await db.execute(
                    select(WebhookEndpoint).where(WebhookEndpoint.id == endpoint_id)
                )
                ep = result.scalar_one_or_none()
                if not ep or not ep.is_active:
                    return

                body = json.dumps(
                    {
                        "event": event_type.value,
                        "id": event_id,
                        "created_at": datetime.now(UTC).isoformat(),
                        "data": payload,
                    }
                ).encode()

                from saas.crypto import decrypt as _decrypt_secret

                signature = sign_payload(body, _decrypt_secret(ep.secret))

                headers = {
                    "Content-Type": "application/json",
                    "X-AnsiQ-Signature": signature,
                    "X-AnsiQ-Event": event_type.value,
                    "X-AnsiQ-Event-Id": event_id,
                    **ep.headers,
                }

                for attempt in range(1, max(1, ep.retry_count) + 1):
                    try:
                        async with httpx.AsyncClient(timeout=ep.timeout_seconds) as client:
                            response = await client.post(ep.url, content=body, headers=headers)

                        event_update = {
                            "attempt_count": attempt,
                            "last_attempt_at": datetime.now(UTC),
                            "last_response_code": response.status_code,
                            "last_response_body": response.text[:2000],
                        }

                        if 200 <= response.status_code < 300:
                            event_update["status"] = "delivered"
                            event_update["delivered_at"] = datetime.now(UTC)
                        else:
                            event_update["status"] = "failed"

                        await db.execute(
                            update(WebhookEvent)
                            .where(WebhookEvent.id == event_id)
                            .values(**event_update)
                        )
                        await db.commit()

                        if event_update["status"] == "delivered":
                            logger.info(
                                "Webhook %s delivered to %s (attempt %d)",
                                event_id,
                                ep.url,
                                attempt,
                            )
                            return

                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Webhook %s attempt %d failed: %s",
                            event_id,
                            attempt,
                            exc,
                        )

                    if attempt < ep.retry_count:
                        # Non-blocking exponential backoff: 2s, 4s, 8s …
                        await asyncio.sleep(2**attempt)

                logger.error(
                    "Webhook %s failed after %d attempts",
                    event_id,
                    ep.retry_count,
                )
            except Exception:
                logger.exception("Background webhook delivery crashed")

"""Sentry error tracking integration for AnsiQ SaaS."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def init_sentry(
    dsn: str | None = None,
    environment: str = "production",
    traces_sample_rate: float = 0.1,
    **kwargs: Any,
) -> bool:
    """Initialize Sentry SDK for error tracking."""
    dsn = dsn or os.getenv("SENTRY_DSN", "")
    if not dsn:
        logger.info("Sentry DSN not configured — error tracking disabled")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            traces_sample_rate=traces_sample_rate,
            integrations=[
                FastApiIntegration(),
                StarletteIntegration(),
                SqlalchemyIntegration(),
            ],
            send_default_pii=False,
            **kwargs,
        )
        logger.info(
            "Sentry initialized (env=%s, rate=%.1f%%)", environment, traces_sample_rate * 100
        )
        return True
    except ImportError:
        logger.warning("sentry-sdk not installed — install with: pip install ansiq[saas]")
        return False
    except Exception as e:
        logger.error("Failed to initialize Sentry: %s", e)
        return False

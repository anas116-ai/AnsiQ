"""Rate limiting middleware for the AnsiQ API.

Provides per-IP rate limiting with configurable limits,
burst protection, and standard rate limit headers.

Configuration via environment variables:
    ANSIQ_RATE_LIMIT        — max requests per window (default: 100)
    ANSIQ_RATE_LIMIT_WINDOW — window in seconds (default: 60)
    ANSIQ_RATE_BURST        — burst limit (default: 20)

Headers set on every response:
    X-RateLimit-Limit
    X-RateLimit-Remaining
    X-RateLimit-Reset
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# ── Configuration ──

DEFAULT_LIMIT = int(os.environ.get("ANSIQ_RATE_LIMIT", "100"))
DEFAULT_WINDOW = int(os.environ.get("ANSIQ_RATE_LIMIT_WINDOW", "60"))
DEFAULT_BURST = int(os.environ.get("ANSIQ_RATE_BURST", "20"))

# Paths excluded from rate limiting
EXCLUDED_PATHS = {"/api/health", "/docs", "/redoc", "/openapi.json", "/dashboard", "/"}


class RateLimitEntry:
    """Tracks request count and reset time for a single client."""

    __slots__ = ("count", "burst_count", "reset_at", "burst_reset_at")

    def __init__(self, window: int):
        now = time.time()
        self.count: int = 0
        self.burst_count: int = 0
        self.reset_at: float = now + window
        self.burst_reset_at: float = now + 1  # burst resets every second


class RateLimitMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that enforces per-IP rate limits.

    Two-tier system:
    - Standard limit: max requests per window (e.g., 100 per 60s)
    - Burst limit: max requests per second (e.g., 20 per 1s)

    Returns 429 Too Many Requests when either limit is exceeded.
    """

    def __init__(
        self,
        app: ASGIApp,
        limit: int = DEFAULT_LIMIT,
        window: int = DEFAULT_WINDOW,
        burst: int = DEFAULT_BURST,
    ):
        super().__init__(app)
        self.limit = limit
        self.window = window
        self.burst = burst
        self._entries: dict[str, RateLimitEntry] = {}
        self._lock = asyncio.Lock()
        logger.info(
            "Rate limiting: %d requests per %ds, burst %d per second",
            limit,
            window,
            burst,
        )

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from headers, falling back to host."""
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP", "")
        if real_ip:
            return real_ip
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip excluded paths
        if request.method == "GET" and request.url.path in EXCLUDED_PATHS:
            return await call_next(request)

        client_ip = self._get_client_ip(request)

        async with self._lock:
            now = time.time()
            entry = self._entries.get(client_ip)

            if entry is None or now >= entry.reset_at:
                entry = RateLimitEntry(self.window)
                self._entries[client_ip] = entry

            # Reset burst counter every second
            if now >= entry.burst_reset_at:
                entry.burst_count = 0
                entry.burst_reset_at = now + 1

            entry.count += 1
            entry.burst_count += 1

            # Check limits
            if entry.count > self.limit or entry.burst_count > self.burst:
                retry_after = int(max(entry.reset_at - now, entry.burst_reset_at - now) + 1)
                logger.warning(
                    "Rate limit exceeded for %s: %d requests in window",
                    client_ip,
                    entry.count,
                )
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": "Too Many Requests",
                        "retry_after_seconds": retry_after,
                        "limit": self.limit,
                        "burst_limit": self.burst,
                    },
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(self.limit),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(int(entry.reset_at)),
                    },
                )

        # Process the request
        response = await call_next(request)

        # Add rate limit headers
        remaining = max(0, self.limit - entry.count)
        response.headers["X-RateLimit-Limit"] = str(self.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(entry.reset_at))

        return response


def create_rate_limit_middleware(
    app: ASGIApp,
    limit: int | None = None,
    window: int | None = None,
    burst: int | None = None,
) -> RateLimitMiddleware:
    """Factory function to create the rate limit middleware with overridable defaults."""
    return RateLimitMiddleware(
        app=app,
        limit=limit if limit is not None else DEFAULT_LIMIT,
        window=window if window is not None else DEFAULT_WINDOW,
        burst=burst if burst is not None else DEFAULT_BURST,
    )

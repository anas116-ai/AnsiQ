"""AnsiQ SaaS — FastAPI production application.

This is the main entry point for the SaaS API server. All routes,
middleware, and lifecycle hooks are registered here.

Fixes vs. the original implementation:
  * Logging is configured BEFORE any application logging happens.
  * Production startup validates JWT/secret strength.
  * CORS no longer uses ``*`` for methods/headers.
  * ``/ready`` does not leak DB error strings to the client.
  * Adds a Prometheus ``/metrics`` endpoint.
  * Adds request-ID middleware for log correlation.
  * Adds a slowapi-based per-IP rate limiter.
  * Uses ``ansiq.__version__`` consistently.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

import ansiq
from ansiq.saas.logging import setup_logging
from ansiq.saas.sentry import init_sentry
from saas.config import config
from saas.database import AsyncSessionLocal, close_db, init_db

logger = logging.getLogger("ansiq.saas")


# ── Lifespan ────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifecycle: startup/shutdown.

    Logging is configured *first* so every subsequent log line uses the
    production JSON handler. In production we also refuse to start
    when secrets look like default placeholders.
    """
    # 1) Logging first.
    setup_logging(
        level=config.log_level,
        environment=config.environment,
        json_format=True,
    )

    # 2) Validate secrets for the current environment.
    try:
        config.validate_for_environment()
    except RuntimeError as exc:
        # In production we want a fatal exit. In other environments
        # log loudly but continue so dev tooling still works.
        if config.is_production:
            logger.critical(str(exc))
            raise SystemExit(1) from exc
        logger.error("Insecure configuration detected: %s", exc)

    # 3) Optional Sentry.
    init_sentry(environment=config.environment)

    logger.info(
        "Starting AnsiQ SaaS server (env=%s, version=%s)",
        config.environment,
        ansiq.__version__,
    )

    # 4) Database tables in dev only — production must use migrations.
    if config.environment == "development":
        try:
            await init_db()
            logger.info("Database tables created (dev mode)")
        except Exception as exc:  # noqa: BLE001
            logger.warning("init_db skipped: %s", exc)

    yield

    await close_db()
    logger.info("AnsiQ SaaS server shut down")


# ── App ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AnsiQ API",
    description="AnsiQ — Intelligent Agent Orchestration Platform",
    version=ansiq.__version__,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)


# ── CORS (locked down) ──────────────────────────────────────────────────

# When ``*`` is in the CORS origins list we must disable credentials
# (browsers reject that combination). For non-wildcard deployments we
# whitelist only the HTTP methods and headers the API actually uses.
_cors_origins = config.security.cors_origins
if "*" in _cors_origins:
    _allow_credentials = False
    _allow_origins = ["*"]
else:
    _allow_credentials = True
    _allow_origins = _cors_origins

_ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
_ALLOWED_HEADERS = [
    "Authorization",
    "Content-Type",
    "X-Requested-With",
    "X-Request-ID",
    "Accept",
    "Origin",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=_allow_credentials,
    allow_methods=_ALLOWED_METHODS,
    allow_headers=_ALLOWED_HEADERS,
    expose_headers=["X-Request-ID"],
)


# ── Middleware ──────────────────────────────────────────────────────────


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """Attach a unique request ID to every request/response.

    Honours an incoming ``X-Request-ID`` header (so an upstream proxy
    can correlate), otherwise generates a fresh UUID4.
    """
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.request_id = rid
    start = time.time()
    response = await call_next(request)
    duration_ms = (time.time() - start) * 1000
    response.headers["X-Request-ID"] = rid
    logger.info(
        "%s %s -> %d in %.1fms (rid=%s)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        rid,
    )
    return response


# ── Health & Readiness ──────────────────────────────────────────────────


@app.get("/health", tags=["System"])
async def health_check():
    """Basic liveness check (no DB)."""
    return {"status": "healthy", "version": ansiq.__version__}


@app.get("/ready", tags=["System"])
async def readiness_check():
    """Readiness probe — checks DB connectivity without leaking details."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ready", "database": "connected"}
    except Exception as exc:  # noqa: BLE001
        # Never leak the underlying error string to the caller — it can
        # contain database URLs, hostnames, or driver internals.
        logger.exception("Readiness check failed")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "not_ready",
                "database": "unreachable",
                "error": str(exc.__class__.__name__),
            },
        )


@app.get("/version", tags=["System"])
async def version():
    return {
        "service": "ansiq",
        "version": ansiq.__version__,
        "environment": config.environment,
        "docs": "/docs",
    }


# ── Prometheus metrics (optional) ──────────────────────────────────────

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        REGISTRY,
        Counter,
        Histogram,
        generate_latest,
    )
    from starlette.responses import Response as StarletteResponse

    # Use unique metric names to support module reloading (tests, dev
    # servers with --reload, etc.) without "Duplicated timeseries"
    # errors from the default global registry.
    _METRIC_PREFIX = "ansiq_"

    def _get_or_create_counter(name, doc, labels):
        try:
            return Counter(name, doc, labels)
        except ValueError:
            # Already registered (e.g., after a reload); look it up.
            for collector in list(REGISTRY._collector_to_names):
                if name in REGISTRY._collector_to_names[collector]:
                    return collector
            raise

    def _get_or_create_histogram(name, doc, labels):
        try:
            return Histogram(name, doc, labels)
        except ValueError:
            for collector in list(REGISTRY._collector_to_names):
                if name in REGISTRY._collector_to_names[collector]:
                    return collector
            raise

    HTTP_REQUESTS = _get_or_create_counter(
        _METRIC_PREFIX + "http_requests_total",
        "Total HTTP requests",
        ["method", "path", "status"],
    )
    HTTP_LATENCY = _get_or_create_histogram(
        _METRIC_PREFIX + "http_request_duration_seconds",
        "HTTP request latency in seconds",
        ["method", "path"],
    )

    @app.middleware("http")
    async def prometheus_middleware(request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        HTTP_REQUESTS.labels(
            method=request.method,
            path=request.url.path,
            status=response.status_code,
        ).inc()
        HTTP_LATENCY.labels(method=request.method, path=request.url.path).observe(
            time.time() - start
        )
        return response

    @app.get("/metrics", tags=["System"], include_in_schema=False)
    async def metrics():
        return StarletteResponse(
            generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )

    _METRICS_ENABLED = True
except ImportError:  # pragma: no cover
    _METRICS_ENABLED = False
    logger.debug("prometheus_client not installed; /metrics disabled")


# ── Slowapi rate limiting (optional) ───────────────────────────────────

try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.util import get_remote_address

    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=[
            f"{config.security.rate_limit_per_minute}/minute",
        ],
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    _RATE_LIMIT_ENABLED = True
except ImportError:  # pragma: no cover
    _RATE_LIMIT_ENABLED = False
    logger.debug("slowapi not installed; per-route rate limits disabled")


# ── Error handlers ──────────────────────────────────────────────────────


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    rid = getattr(request.state, "request_id", "-")
    logger.exception(
        "Unhandled exception on %s %s (rid=%s, type=%s)",
        request.method,
        request.url.path,
        rid,
        exc.__class__.__name__,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": exc.__class__.__name__},
    )


# ── Static & template routes ───────────────────────────────────────────

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

if TEMPLATES_DIR.exists():
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @app.get("/", response_class=HTMLResponse, tags=["Web"])
    async def landing_page():
        html = TEMPLATES_DIR / "index.html"
        if html.exists():
            return HTMLResponse(content=html.read_text(encoding="utf-8"))
        return HTMLResponse(content="<h1>AnsiQ API</h1><p>Running...</p>")


# ── Register routers ────────────────────────────────────────────────────

from saas.routes.account import router as account_router
from saas.routes.agents import router as agents_router
from saas.routes.crews import router as crews_router
from saas.routes.tasks import router as tasks_router
from saas.routes.api import router as api_router
from saas.routes.auth import router as auth_router

app.include_router(auth_router)
app.include_router(api_router)
app.include_router(account_router)
app.include_router(agents_router)
app.include_router(crews_router)
app.include_router(tasks_router)


# Stripe webhook (mounted at /webhooks/stripe — outside /api/v1 so it
# doesn't require an Authorization header; Stripe signs the payload).
from fastapi import Request as _Request


@app.post("/webhooks/stripe", tags=["Billing"], include_in_schema=False)
async def stripe_webhook(request: _Request):
    from saas.billing import billing_service

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        result = await billing_service.handle_webhook(payload, sig)
        return result
    except Exception as exc:
        logger.exception("Stripe webhook processing failed")
        return JSONResponse(
            status_code=400,
            content={"error": type(exc).__name__},
        )


logger.info("Registered routes: %s", [route.path for route in app.routes])

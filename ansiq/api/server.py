"""FastAPI server — creates and runs the AnsiQ REST API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ansiq import __version__
from ansiq.api.auth import verify_api_key
from ansiq.api.ratelimit import RateLimitMiddleware
from ansiq.api.routes import api_router
from ansiq.api.routes.ws import router as ws_router
from ansiq.api.state import get_app_state

logger = logging.getLogger(__name__)


# ── Lifecycle ──


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — initialize resources on startup, cleanup on shutdown."""
    logger.info("AnsiQ API server starting...")

    # Initialize memory store
    state = get_app_state()
    try:
        from ansiq.memory.fts_store import FTSMemoryStore

        state.memory_store = FTSMemoryStore()
        logger.info("Memory store initialized")
    except Exception as e:
        logger.warning("Failed to initialize memory store: %s", e)

    yield  # Server is running

    # Cleanup
    logger.info("AnsiQ API server shutting down...")


# ── App Factory ──


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AnsiQ API",
        description="Intelligent Agent Orchestration Framework — REST API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS — allow all origins for development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting
    app.add_middleware(RateLimitMiddleware)

    # Mount routes (with optional API key auth as global dependency)
    app.include_router(api_router, dependencies=[Depends(verify_api_key)])

    # WebSocket routes (mounted directly, no /api prefix for WS)
    app.include_router(ws_router)

    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc), "error_code": "INTERNAL_ERROR"},
        )

    # Mount static files (dashboard assets)
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Dashboard — serve the SPA
    @app.get("/dashboard")
    async def dashboard():
        return FileResponse(str(static_dir / "dashboard.html"))

    # Root endpoint — API info JSON
    @app.get("/")
    async def root():
        return {
            "name": "AnsiQ API",
            "version": __version__,
            "docs": "/docs",
            "health": "/api/health",
            "dashboard": "/dashboard",
        }

    return app


# ── Server Runner ──


def run_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    reload: bool = False,
    log_level: str = "info",
) -> None:
    """Start the AnsiQ API server.

    Args:
        host: Host to bind to (default: 0.0.0.0)
        port: Port to listen on (default: 8000)
        reload: Enable auto-reload on file changes (default: False)
        log_level: Uvicorn log level (default: info)
    """
    app = create_app()
    logger.info("Starting AnsiQ API server on http://%s:%d", host, port)
    logger.info("API docs available at http://%s:%d/docs", host, port)

    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )

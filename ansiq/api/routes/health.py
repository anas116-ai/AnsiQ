"""Health check endpoint."""

from __future__ import annotations

import time

from fastapi import APIRouter

from ansiq import __version__
from ansiq.api.models import HealthResponse

router = APIRouter()

_START_TIME = time.time()


@router.get("", response_model=HealthResponse)
async def health():
    """Health check — returns server status, version, and uptime."""
    return HealthResponse(
        status="ok",
        version=__version__,
        uptime_seconds=round(time.time() - _START_TIME, 2),
    )

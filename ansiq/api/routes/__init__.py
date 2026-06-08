"""Route aggregation — mount all sub-routers to the main API router."""

from __future__ import annotations

from fastapi import APIRouter

from ansiq.api.routes.agents import router as agents_router
from ansiq.api.routes.crews import router as crews_router
from ansiq.api.routes.health import router as health_router
from ansiq.api.routes.io import router as io_router
from ansiq.api.routes.knowledge import router as knowledge_router
from ansiq.api.routes.memory import router as memory_router
from ansiq.api.routes.skills import router as skills_router
from ansiq.api.routes.templates import router as templates_router

api_router = APIRouter(prefix="/api")

api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(agents_router, prefix="/agents", tags=["agents"])
api_router.include_router(crews_router, prefix="/crews", tags=["crews"])
api_router.include_router(memory_router, prefix="/memory", tags=["memory"])
api_router.include_router(knowledge_router, prefix="/knowledge", tags=["knowledge"])
api_router.include_router(skills_router, prefix="/skills", tags=["skills"])
api_router.include_router(io_router, prefix="", tags=["import-export"])
api_router.include_router(templates_router, prefix="/templates", tags=["templates"])

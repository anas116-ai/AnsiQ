"""Memory browsing routes — list, search, stats."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from ansiq.api.models import (
    MemoryItem,
    MemoryListResponse,
    MemorySearchRequest,
    MemoryStatsResponse,
)
from ansiq.api.state import get_app_state

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=MemoryListResponse)
async def list_memories(limit: int = Query(default=20, le=100)):
    """List recent memories from the default FTS store."""
    state = get_app_state()
    store = state.memory_store
    if not store:
        raise HTTPException(status_code=503, detail="Memory store not initialized")

    try:
        memories = store.get_recent(limit=limit)
        items = []
        for mem in memories:
            items.append(
                MemoryItem(
                    rowid=mem.get("rowid", 0),
                    content=mem.get("content", ""),
                    summary=mem.get("summary", "") or mem.get("content", "")[:80],
                    timestamp=mem.get("timestamp", ""),
                    agent_id=mem.get("agent_id", ""),
                    tags=mem.get("tags", []),
                )
            )
        return MemoryListResponse(memories=items, total=len(items))
    except Exception as e:
        logger.error("Memory list failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search", response_model=MemoryListResponse)
async def search_memories(req: MemorySearchRequest):
    """Search memories by query text."""
    state = get_app_state()
    store = state.memory_store
    if not store:
        raise HTTPException(status_code=503, detail="Memory store not initialized")

    try:
        results = store.search(req.query, limit=req.limit)
        items = []
        for mem in results:
            items.append(
                MemoryItem(
                    rowid=mem.get("rowid", 0),
                    content=mem.get("content", ""),
                    summary=mem.get("summary", "") or mem.get("content", "")[:80],
                    timestamp=mem.get("timestamp", ""),
                    agent_id=mem.get("agent_id", ""),
                    tags=mem.get("tags", []),
                )
            )
        return MemoryListResponse(memories=items, total=len(items))
    except Exception as e:
        logger.error("Memory search failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats", response_model=MemoryStatsResponse)
async def memory_stats():
    """Get memory statistics."""
    state = get_app_state()
    store = state.memory_store
    if not store:
        raise HTTPException(status_code=503, detail="Memory store not initialized")

    try:
        total = store.count()
        db_path = getattr(store, "db_path", "")
        return MemoryStatsResponse(
            total_memories=total,
            total_agents=1,
            db_path=str(db_path),
        )
    except Exception as e:
        logger.error("Memory stats failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

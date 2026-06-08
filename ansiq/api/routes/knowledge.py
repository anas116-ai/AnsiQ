"""Knowledge/RAG routes — add sources, query, stats."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from ansiq.api.models import (
    KnowledgeQueryRequest,
    KnowledgeQueryResponse,
    KnowledgeQueryResult,
    KnowledgeSourceRequest,
    KnowledgeSourceResponse,
    KnowledgeStatsResponse,
)
from ansiq.api.state import get_app_state

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/sources", response_model=KnowledgeSourceResponse, status_code=201)
async def add_knowledge_source(req: KnowledgeSourceRequest):
    """Add a knowledge source and index it for RAG."""
    state = get_app_state()

    # Create the appropriate source
    if req.source_type == "text":
        from ansiq.knowledge.source import TextSource

        source = TextSource(name=req.name, text=req.content)
    elif req.source_type == "file":
        from pathlib import Path

        from ansiq.knowledge.source import FileSource

        source = FileSource(name=req.name, file_path=Path(req.file_path))
    elif req.source_type == "url":
        from ansiq.knowledge.source import URLSource

        source = URLSource(name=req.name, url=req.url)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported source type: {req.source_type}")

    # Ensure RAG engine exists
    if not state.rag_engine:
        from ansiq.knowledge.engine import RAGEngine

        state.rag_engine = RAGEngine()

    try:
        success = await state.rag_engine.add_source(source)
        stats = state.rag_engine.get_stats()
        chunks_count = stats.get("store", {}).get("total_chunks", 0)
        return KnowledgeSourceResponse(
            name=req.name,
            source_type=req.source_type,
            chunks_count=chunks_count,
            added=success,
        )
    except Exception as e:
        logger.error("Failed to add knowledge source: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sources", response_model=dict)
async def list_knowledge_sources():
    """List all knowledge sources."""
    state = get_app_state()
    if not state.rag_engine:
        return {"sources": [], "total": 0}

    stats = state.rag_engine.get_stats()
    return {
        "sources": stats.get("sources", []),
        "total": len(stats.get("sources", [])),
    }


@router.post("/query", response_model=KnowledgeQueryResponse)
async def query_knowledge(req: KnowledgeQueryRequest):
    """Query knowledge sources for relevant context."""
    state = get_app_state()
    if not state.rag_engine:
        raise HTTPException(status_code=503, detail="RAG engine not initialized")

    try:
        results = state.rag_engine.query(req.query, top_k=req.top_k)
        items = []
        for r in results:
            items.append(
                KnowledgeQueryResult(
                    text=r.get("text", ""),
                    source=r.get("source", ""),
                    score=r.get("score", 0.0),
                    chunk_index=r.get("chunk_index", 0),
                )
            )
        return KnowledgeQueryResponse(results=items, total=len(items))
    except Exception as e:
        logger.error("Knowledge query failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats", response_model=KnowledgeStatsResponse)
async def knowledge_stats():
    """Get knowledge/RAG system statistics."""
    state = get_app_state()
    if not state.rag_engine:
        return KnowledgeStatsResponse(total_chunks=0, total_sources=0)

    stats = state.rag_engine.get_stats()
    store = stats.get("store", {})
    return KnowledgeStatsResponse(
        total_chunks=store.get("total_chunks", 0),
        total_sources=len(stats.get("sources", [])),
        vocabulary_size=store.get("vocabulary_size", 0),
        embedded_chunks=store.get("embedded_chunks", 0),
    )

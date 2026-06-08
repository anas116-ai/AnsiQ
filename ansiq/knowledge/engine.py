"""RAG Engine — retrieves knowledge and injects it into prompts.

Orchestrates the full RAG pipeline:
1. Accept knowledge sources
2. Chunk and index them
3. On query, retrieve relevant chunks
4. Format as context for LLM prompts
"""

from __future__ import annotations

import logging
from typing import Any

from ansiq.knowledge.source import KnowledgeSource
from ansiq.knowledge.store import VectorKnowledgeStore

logger = logging.getLogger(__name__)


class RAGEngine:
    """Retrieval-Augmented Generation engine.

    Manages knowledge sources and provides relevant context
    for agent prompts. Supports vector embeddings for semantic search.

    Example:
        from ansiq.embeddings.openai_provider import OpenAIEmbedding

        engine = RAGEngine(
            store=VectorKnowledgeStore(
                embedding_provider=OpenAIEmbedding()
            )
        )
        await engine.add_source(source)
        context = engine.get_context("user query")
    """

    def __init__(
        self,
        store: VectorKnowledgeStore | None = None,
        embedding_provider: Any | None = None,
    ):
        if store is None:
            store = VectorKnowledgeStore(embedding_provider=embedding_provider)
        self.store = store
        self._sources: dict[str, KnowledgeSource] = {}

    async def add_source(self, source: KnowledgeSource) -> bool:
        """Add a knowledge source and index its content.

        Automatically generates embeddings if an embedding provider
        is configured on the underlying store.

        Returns True if content was successfully indexed.
        """
        try:
            chunks = await source.get_chunks()
            if chunks:
                # Use async add to generate embeddings automatically
                count = await self.store.add_chunks_async(chunks)
                self._sources[source.name] = source
                logger.info(
                    "Indexed %d chunks from source '%s'%s",
                    count,
                    source.name,
                    " (with embeddings)" if self.store._embedding_provider else "",
                )
                return count > 0
            logger.warning("No content found in source '%s'", source.name)
            return False
        except Exception as e:
            logger.error("Failed to index source '%s': %s", source.name, e)
            return False

    async def add_sources(self, sources: list[KnowledgeSource]) -> int:
        """Add multiple knowledge sources. Returns count of successful indexes."""
        success = 0
        for source in sources:
            if await self.add_source(source):
                success += 1
        return success

    def query(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        """Search for relevant knowledge chunks."""
        return self.store.search(query, top_k=top_k)

    def get_context(self, query: str, top_k: int = 3, max_chars: int = 2000) -> str:
        """Get formatted context string for LLM injection."""
        return self.store.get_formatted_context(query, top_k=top_k, max_chars=max_chars)

    def get_stats(self) -> dict[str, Any]:
        """Get RAG engine statistics."""
        store_stats = self.store.get_stats()
        return {
            "sources": list(self._sources.keys()),
            "store": store_stats,
            "embeddings_enabled": store_stats.get("embedded_chunks", 0) > 0,
        }

    async def clear(self) -> None:
        """Clear all sources and stored knowledge."""
        self._sources.clear()
        self.store.clear()

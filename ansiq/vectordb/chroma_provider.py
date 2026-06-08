"""ChromaDB vector database provider.

Uses ChromaDB as the backend for persistent vector storage with
metadata filtering. Supports both in-memory and persistent modes.

Requires: pip install chromadb
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ansiq.vectordb.base import SearchResult, VectorDBProvider

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path.home() / ".ansiq" / "vectordb"


class ChromaDBProvider(VectorDBProvider):
    """Vector database using ChromaDB backend.

    Supports persistent storage to disk and in-memory modes.

    Example:
        db = ChromaDBProvider(persist_path=\"./my_vectors\")
        await db.add(\"doc1\", [0.1, 0.2, ...], {\"text\": \"Hello\"})
        results = await db.search([0.1, 0.2, ...], top_k=5)
    """

    def __init__(
        self,
        collection_name: str = "ansiq_vectors",
        persist_path: str | None = None,
        distance_func: str = "cosine",
    ):
        self.collection_name = collection_name
        self.persist_path = str(persist_path) if persist_path else None
        self.distance_func = distance_func
        self._client: Any = None
        self._collection: Any = None

    def _get_client(self):
        """Lazy-initialize the ChromaDB client."""
        if self._client is not None:
            return self._client

        try:
            import chromadb
        except ImportError:
            raise ImportError(
                "chromadb is required for ChromaDBProvider. Install: pip install chromadb"
            )

        if self.persist_path:
            self._client = chromadb.PersistentClient(path=self.persist_path)
            logger.info("ChromaDB persistent client initialized at %s", self.persist_path)
        else:
            self._client = chromadb.EphemeralClient()
            logger.info("ChromaDB ephemeral client initialized")

        return self._client

    def _get_collection(self, vector: list[float] | None = None):
        """Lazy-initialize the ChromaDB collection."""
        if self._collection is not None:
            return self._collection

        client = self._get_client()

        try:
            self._collection = client.get_collection(self.collection_name)
            logger.debug("Using existing collection: %s", self.collection_name)
        except Exception:
            self._collection = client.create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": self.distance_func},
            )
            logger.info("Created collection: %s", self.collection_name)

        return self._collection

    async def add(
        self,
        id: str,
        vector: list[float],
        payload: dict[str, Any] | None = None,
    ) -> bool:
        """Add a single vector to ChromaDB."""
        collection = self._get_collection(vector)

        # ChromaDB rejects empty metadata dicts — only include if non-empty
        metadata = payload if payload and len(payload) > 0 else None
        documents = [payload.get("text", "")] if payload and "text" in payload else None

        try:
            kwargs: dict[str, Any] = {
                "ids": [id],
                "embeddings": [vector],
            }
            if metadata is not None:
                kwargs["metadatas"] = [metadata]
            if documents:
                kwargs["documents"] = documents
            collection.add(**kwargs)
            return True
        except Exception as e:
            logger.error("Failed to add vector '%s': %s", id, e)
            return False

    async def add_batch(
        self,
        ids: list[str],
        vectors: list[list[float]],
        payloads: list[dict[str, Any]] | None = None,
    ) -> int:
        """Add multiple vectors to ChromaDB in batch."""
        if not ids or not vectors:
            return 0

        collection = self._get_collection(vectors[0])

        # Only include non-empty metadata (ChromaDB rejects {} and empty lists)
        metadatas = None
        documents = None
        if payloads:
            non_empty = [p for p in payloads if p and len(p) > 0]
            if non_empty:
                metadatas = non_empty
            documents = [p.get("text", None) for p in payloads]
            if not any(documents):
                documents = None

        try:
            kwargs: dict[str, Any] = {
                "ids": ids,
                "embeddings": vectors,
            }
            if metadatas is not None:
                kwargs["metadatas"] = metadatas
            if documents:
                kwargs["documents"] = documents
            collection.add(**kwargs)
            return len(ids)
        except Exception as e:
            logger.error("Failed to add batch of %d vectors: %s", len(ids), e)
            return 0

    async def search(
        self,
        vector: list[float],
        top_k: int = 10,
        filter: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Search for similar vectors in ChromaDB."""
        collection = self._get_collection(vector)

        try:
            where = filter if filter else None
            results = collection.query(
                query_embeddings=[vector],
                n_results=min(top_k, 100),
                where=where,
                include=["metadatas", "distances"],
            )

            if not results["ids"] or not results["ids"][0]:
                return []

            search_results = []
            for i, doc_id in enumerate(results["ids"][0]):
                distance = results["distances"][0][i] if results.get("distances") else 1.0
                # Convert distance to similarity score (1 - distance for cosine)
                score = max(0.0, 1.0 - distance)
                payload = results["metadatas"][0][i] if results.get("metadatas") else {}

                search_results.append(
                    SearchResult(
                        id=doc_id,
                        score=round(score, 4),
                        payload=payload,
                    )
                )

            return search_results

        except Exception as e:
            logger.error("Vector search failed: %s", e)
            return []

    async def delete(self, id: str) -> bool:
        """Delete a vector from ChromaDB."""
        try:
            collection = self._get_collection()
            collection.delete(ids=[id])
            return True
        except Exception as e:
            logger.warning("Failed to delete vector '%s': %s", id, e)
            return False

    async def delete_batch(self, ids: list[str]) -> int:
        """Delete multiple vectors from ChromaDB."""
        if not ids:
            return 0
        try:
            collection = self._get_collection()
            collection.delete(ids=ids)
            return len(ids)
        except Exception as e:
            logger.warning("Failed to delete batch: %s", e)
            return 0

    async def count(self) -> int:
        """Get vector count from ChromaDB."""
        try:
            collection = self._get_collection()
            return collection.count()
        except Exception:
            return 0

    async def clear(self) -> None:
        """Delete and recreate the collection."""
        try:
            client = self._get_client()
            client.delete_collection(self.collection_name)
            self._collection = None
            logger.info("Cleared collection: %s", self.collection_name)
        except Exception as e:
            logger.warning("Failed to clear collection: %s", e)

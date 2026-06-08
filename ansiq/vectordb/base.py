"""Abstract base for vector database backends.

A VectorDBProvider stores embeddings and retrieves them via
semantic search. Supports multiple backends (ChromaDB, FAISS, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class SearchResult:
    """Result of a vector search query."""

    def __init__(
        self,
        id: str,
        score: float,
        payload: dict[str, Any] | None = None,
    ):
        self.id = id
        self.score = score
        self.payload = payload or {}

    def __repr__(self) -> str:
        return f"SearchResult(id='{self.id}', score={self.score:.4f})"


class VectorDBProvider(ABC):
    """Abstract base for vector database backends.

    Subclasses must implement add(), search(), delete(), and count().
    """

    @abstractmethod
    async def add(
        self,
        id: str,
        vector: list[float],
        payload: dict[str, Any] | None = None,
    ) -> bool:
        """Add a vector with associated metadata to the database.

        Args:
            id: Unique identifier for this vector.
            vector: The embedding vector.
            payload: Optional metadata to store with the vector.

        Returns:
            True if successful.
        """
        ...

    @abstractmethod
    async def add_batch(
        self,
        ids: list[str],
        vectors: list[list[float]],
        payloads: list[dict[str, Any]] | None = None,
    ) -> int:
        """Add multiple vectors in batch.

        Args:
            ids: List of unique identifiers.
            vectors: List of embedding vectors.
            payloads: Optional list of metadata dicts.

        Returns:
            Number of vectors added.
        """
        ...

    @abstractmethod
    async def search(
        self,
        vector: list[float],
        top_k: int = 10,
        filter: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Search for similar vectors.

        Args:
            vector: Query embedding vector.
            top_k: Maximum number of results.
            filter: Optional metadata filter.

        Returns:
            List of SearchResults sorted by similarity (descending).
        """
        ...

    @abstractmethod
    async def delete(self, id: str) -> bool:
        """Delete a vector by ID.

        Returns:
            True if the vector was found and deleted.
        """
        ...

    @abstractmethod
    async def delete_batch(self, ids: list[str]) -> int:
        """Delete multiple vectors by IDs.

        Returns:
            Number of vectors deleted.
        """
        ...

    @abstractmethod
    async def count(self) -> int:
        """Get total number of vectors in the database."""
        ...

    @abstractmethod
    async def clear(self) -> None:
        """Remove all vectors from the database."""
        ...

    def cosine_similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """Compute cosine similarity between two vectors (for testing)."""
        import math

        dot = sum(a * b for a, b in zip(vec1, vec2, strict=False))
        n1 = math.sqrt(sum(a * a for a in vec1))
        n2 = math.sqrt(sum(b * b for b in vec2))
        if n1 == 0 or n2 == 0:
            return 0.0
        return dot / (n1 * n2)

"""Abstract base for embedding providers.

An EmbeddingProvider converts text into vector representations
that can be used for semantic search and similarity comparison.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class EmbeddingResult:
    """Result of an embedding operation."""

    def __init__(
        self,
        vector: list[float],
        dimensions: int,
        model: str,
        provider: str,
    ):
        self.vector = vector
        self.dimensions = dimensions
        self.model = model
        self.provider = provider

    def __repr__(self) -> str:
        return (
            f"EmbeddingResult(dimensions={self.dimensions}, "
            f"model='{self.model}', provider='{self.provider}')"
        )


class EmbeddingProvider(ABC):
    """Abstract base for all embedding providers.

    Subclasses must implement embed() and embed_batch().
    """

    @abstractmethod
    async def embed(self, text: str) -> EmbeddingResult:
        """Convert a single text string into a vector embedding.

        Args:
            text: The text to embed.

        Returns:
            An EmbeddingResult containing the vector and metadata.
        """
        ...

    @abstractmethod
    async def embed_batch(
        self, texts: list[str], show_progress: bool = False
    ) -> list[EmbeddingResult]:
        """Convert multiple texts into vector embeddings.

        Args:
            texts: List of texts to embed.
            show_progress: Whether to show a progress bar.

        Returns:
            List of EmbeddingResults in the same order as inputs.
        """
        ...

    @abstractmethod
    def get_dimensions(self) -> int:
        """Get the dimensionality of embeddings produced by this provider."""
        ...

    def cosine_similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """Compute cosine similarity between two vectors.

        Args:
            vec1: First vector.
            vec2: Second vector.

        Returns:
            Cosine similarity score between 0 and 1.
        """
        import math

        if len(vec1) != len(vec2):
            raise ValueError(f"Vector dimension mismatch: {len(vec1)} vs {len(vec2)}")

        dot = sum(a * b for a, b in zip(vec1, vec2, strict=False))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot / (norm1 * norm2)

    def get_config(self) -> dict[str, Any]:
        """Get provider configuration for serialization."""
        return {
            "provider": self.__class__.__name__,
            "dimensions": self.get_dimensions(),
        }

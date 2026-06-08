"""Local embedding provider — uses sentence-transformers for completely local embeddings.

Requires: pip install sentence-transformers

This is the opt-in local provider for users who want:
- Zero external API calls
- Complete privacy (data never leaves the machine)
- Offline operation

Model is loaded lazily on first embed() call.
"""

from __future__ import annotations

import logging
from typing import Any

from ansiq.embeddings.base import EmbeddingProvider, EmbeddingResult

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "all-MiniLM-L6-v2"
"""384-dimension model, fast and lightweight (~80MB)."""


class LocalEmbedding(EmbeddingProvider):
    """Embedding provider using local sentence-transformers models.

    The model is loaded on first call to embed()/embed_batch().
    Uses all-MiniLM-L6-v2 by default (384 dimensions, ~80MB).

    Example:
        provider = LocalEmbedding()
        result = await provider.embed("Hello world")
        print(result.vector[:5])
    """

    def __init__(
        self,
        model_name: str = _DEFAULT_MODEL,
        device: str | None = None,
        show_progress: bool = True,
    ):
        self.model_name = model_name
        self.device = device
        self._show_progress = show_progress
        self._model: Any = None
        self._dimensions: int = 0  # resolved lazily in _load_model()

    def _load_model(self) -> None:
        """Lazy-load the sentence-transformers model."""
        if self._model is not None:
            return

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers is required for LocalEmbedding. "
                "Install: pip install 'ansiq[embeddings]' "
                "or pip install sentence-transformers"
            )

        logger.info(
            "Loading embedding model '%s' (first load downloads ~80MB)...",
            self.model_name,
        )

        kwargs: dict[str, Any] = {}
        if self.device:
            kwargs["device"] = self.device

        self._model = SentenceTransformer(self.model_name, **kwargs)
        # Use get_embedding_dimension (newer API) with fallback to deprecated name
        if hasattr(self._model, "get_embedding_dimension"):
            self._dimensions = self._model.get_embedding_dimension()
        else:
            self._dimensions = self._model.get_sentence_embedding_dimension()
        logger.info(
            "Embedding model loaded: %s (%d dimensions)",
            self.model_name,
            self._dimensions,
        )

    async def embed(self, text: str) -> EmbeddingResult:
        """Embed a single text string."""
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(
        self, texts: list[str], show_progress: bool = False
    ) -> list[EmbeddingResult]:
        """Embed multiple texts using the local model.

        Args:
            texts: List of texts to embed.
            show_progress: Override to show progress bar.

        Returns:
            List of EmbeddingResults.
        """
        if not texts:
            return []

        self._load_model()

        # Use _show_progress from init, or override if provided
        show = show_progress or self._show_progress

        # sentence-transformers is synchronous; run in executor
        import asyncio

        loop = asyncio.get_running_loop()

        def _encode() -> list[list[float]]:
            embeddings = self._model.encode(
                texts,
                show_progress_bar=show,
                normalize_embeddings=True,
            )
            return [emb.tolist() for emb in embeddings]

        vectors = await loop.run_in_executor(None, _encode)

        return [
            EmbeddingResult(
                vector=vec,
                dimensions=self._dimensions,
                model=self.model_name,
                provider="local",
            )
            for vec in vectors
        ]

    def get_dimensions(self) -> int:
        """Get embedding dimensions."""
        return self._dimensions

    def get_config(self) -> dict[str, Any]:
        return {
            "provider": "LocalEmbedding",
            "model": self.model_name,
            "dimensions": self._dimensions,
            "device": self.device,
        }

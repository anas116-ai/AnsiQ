"""OpenAI embedding provider — uses OpenAI's text-embedding API.

Lightweight: only requires httpx for HTTP calls.
No heavy ML dependencies needed.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from ansiq.embeddings.base import EmbeddingProvider, EmbeddingResult

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "text-embedding-3-small"
_DEFAULT_DIMENSIONS = 1536


class OpenAIEmbedding(EmbeddingProvider):
    """Embedding provider using OpenAI's API.

    Requires OPENAI_API_KEY environment variable or an api_key argument.
    Uses text-embedding-3-small by default (1536 dimensions).

    Example:
        provider = OpenAIEmbedding(api_key="sk-...")
        result = await provider.embed("Hello world")
        print(result.vector[:5])  # First 5 dimensions
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = _DEFAULT_MODEL,
        dimensions: int | None = None,
        base_url: str | None = None,
        max_retries: int = 3,
    ):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not self.api_key:
            logger.warning(
                "No OpenAI API key provided. Set OPENAI_API_KEY env var "
                "or pass api_key to OpenAIEmbedding()."
            )
        self.model = model
        self._dimensions = dimensions or _DEFAULT_DIMENSIONS
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.max_retries = max_retries
        self._http_client: Any = None

    async def _get_client(self):
        """Lazy-create httpx client."""
        if self._http_client is None:
            try:
                import httpx
            except ImportError:
                raise RuntimeError(
                    "httpx is required for OpenAIEmbedding. Install: pip install httpx"
                )
            self._http_client = httpx.AsyncClient(
                timeout=60.0,
                follow_redirects=True,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._http_client

    async def embed(self, text: str) -> EmbeddingResult:
        """Embed a single text string."""
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(
        self, texts: list[str], show_progress: bool = False
    ) -> list[EmbeddingResult]:
        """Embed multiple texts via OpenAI's API.

        Args:
            texts: List of texts to embed.
            show_progress: Ignored for API-based provider.

        Returns:
            List of EmbeddingResults.
        """
        if not texts:
            return []

        if not self.api_key:
            # Return zero vectors as fallback
            return [
                EmbeddingResult(
                    vector=[0.0] * self._dimensions,
                    dimensions=self._dimensions,
                    model=self.model,
                    provider="openai",
                )
                for _ in texts
            ]

        client = await self._get_client()

        # Truncate texts to avoid token limits (max 8192 tokens for -3-small)
        truncated = [t[:32000] for t in texts]

        payload: dict[str, Any] = {
            "model": self.model,
            "input": truncated,
        }
        if self.model == "text-embedding-3-small":
            payload["dimensions"] = self._dimensions

        for attempt in range(self.max_retries):
            try:
                response = await client.post(
                    f"{self.base_url}/embeddings",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

                results: list[EmbeddingResult] = []
                for item in data.get("data", []):
                    results.append(
                        EmbeddingResult(
                            vector=item["embedding"],
                            dimensions=len(item["embedding"]),
                            model=self.model,
                            provider="openai",
                        )
                    )
                return results

            except Exception as e:
                if attempt < self.max_retries - 1:
                    import asyncio

                    wait = 2**attempt
                    logger.warning(
                        "OpenAI embedding attempt %d failed: %s. Retrying in %ds...",
                        attempt + 1,
                        e,
                        wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        "OpenAI embedding failed after %d attempts: %s",
                        self.max_retries,
                        e,
                    )
                    # Return zero vectors as fallback
                    return [
                        EmbeddingResult(
                            vector=[0.0] * self._dimensions,
                            dimensions=self._dimensions,
                            model=self.model,
                            provider="openai",
                        )
                        for _ in texts
                    ]

    def get_dimensions(self) -> int:
        """Get embedding dimensions."""
        return self._dimensions

    def get_config(self) -> dict[str, Any]:
        return {
            "provider": "OpenAIEmbedding",
            "model": self.model,
            "dimensions": self._dimensions,
        }

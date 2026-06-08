"""Vector Embeddings — pluggable embedding providers for semantic search.

Supports:
- OpenAIEmbedding: cloud-based via OpenAI API (zero deps beyond httpx)
- LocalEmbedding: local via sentence-transformers (opt-in, needs torch)
"""

from ansiq.embeddings.base import EmbeddingProvider, EmbeddingResult
from ansiq.embeddings.local_provider import LocalEmbedding
from ansiq.embeddings.openai_provider import OpenAIEmbedding

__all__ = [
    "EmbeddingProvider",
    "EmbeddingResult",
    "OpenAIEmbedding",
    "LocalEmbedding",
]

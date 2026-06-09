"""Tests for the Vector Embeddings system.

Tests the embedding provider abstraction and both implementations:
- EmbeddingProvider base class
- OpenAIEmbedding (cloud)
- LocalEmbedding (sentence-transformers)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ansiq.embeddings.base import EmbeddingProvider, EmbeddingResult
from ansiq.embeddings.local_provider import LocalEmbedding
from ansiq.embeddings.openai_provider import OpenAIEmbedding

try:
    import sentence_transformers  # noqa: F401
    _HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    _HAS_SENTENCE_TRANSFORMERS = False

skipif_no_local = pytest.mark.skipif(
    not _HAS_SENTENCE_TRANSFORMERS,
    reason="sentence-transformers not installed; install with: pip install 'ansiq[embeddings]'",
)


class TestEmbeddingResult:
    """Tests for the EmbeddingResult data class."""

    def test_create_result(self):
        """Test creating an embedding result."""
        result = EmbeddingResult(
            vector=[0.1, 0.2, 0.3],
            dimensions=3,
            model="test-model",
            provider="test",
        )
        assert len(result.vector) == 3
        assert result.dimensions == 3
        assert result.model == "test-model"
        assert result.provider == "test"

    def test_repr(self):
        """Test string representation."""
        result = EmbeddingResult(
            vector=[0.1, 0.2],
            dimensions=2,
            model="m",
            provider="p",
        )
        rep = repr(result)
        assert "dimensions=2" in rep
        assert "model='m'" in rep
        assert "provider='p'" in rep


class TestEmbeddingProviderBase:
    """Tests for the abstract EmbeddingProvider base class."""

    def test_cosine_similarity_identical(self):
        """Test cosine similarity of identical vectors is 1.0."""
        provider = _create_mock_provider()
        similarity = provider.cosine_similarity(
            [1.0, 0.0, 0.0], [1.0, 0.0, 0.0]
        )
        assert similarity == 1.0

    def test_cosine_similarity_orthogonal(self):
        """Test cosine similarity of orthogonal vectors is 0."""
        provider = _create_mock_provider()
        similarity = provider.cosine_similarity(
            [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]
        )
        assert similarity == 0.0

    def test_cosine_similarity_partial(self):
        """Test cosine similarity with partial overlap."""
        provider = _create_mock_provider()
        similarity = provider.cosine_similarity(
            [1.0, 0.0], [0.5, 0.5]
        )
        import math
        expected = 0.5 / (1.0 * math.sqrt(0.5))
        assert abs(similarity - expected) < 0.0001

    def test_cosine_similarity_zero_norm(self):
        """Test cosine similarity with zero vector is 0."""
        provider = _create_mock_provider()
        similarity = provider.cosine_similarity(
            [0.0, 0.0], [1.0, 0.0]
        )
        assert similarity == 0.0

    def test_cosine_similarity_dimension_mismatch(self):
        """Test dimension mismatch raises ValueError."""
        provider = _create_mock_provider()
        with pytest.raises(ValueError, match="dimension mismatch"):
            provider.cosine_similarity([1.0, 0.0], [1.0])


class TestOpenAIEmbedding:
    """Tests for the OpenAI embedding provider."""

    def test_init_no_key(self):
        """Test initialization without API key (should warn but not fail)."""
        provider = OpenAIEmbedding(api_key="")
        assert provider.get_dimensions() == 1536

    def test_get_dimensions(self):
        """Test default dimensions."""
        provider = OpenAIEmbedding(api_key="sk-test")
        assert provider.get_dimensions() == 1536

    def test_get_dimensions_custom(self):
        """Test custom dimensions."""
        provider = OpenAIEmbedding(api_key="sk-test", dimensions=256)
        assert provider.get_dimensions() == 256

    def test_get_config(self):
        """Test config returns metadata."""
        provider = OpenAIEmbedding(api_key="sk-test")
        config = provider.get_config()
        assert config["provider"] == "OpenAIEmbedding"
        assert config["model"] == "text-embedding-3-small"
        assert config["dimensions"] == 1536

    def test_embed_no_key_returns_zero_vector(self):
        """Test that without API key, embedding returns zero vector."""
        provider = OpenAIEmbedding(api_key="")
        import asyncio
        result = asyncio.run(provider.embed("test"))
        assert result.dimensions == 1536
        assert result.provider == "openai"
        assert all(v == 0.0 for v in result.vector[:5])

    def test_embed_batch_empty(self):
        """Test empty batch returns empty list."""
        provider = OpenAIEmbedding(api_key="sk-test")
        import asyncio
        results = asyncio.run(provider.embed_batch([]))
        assert results == []


class TestLocalEmbedding:
    """Tests for the local embedding provider."""

    def test_init_defaults(self):
        """Test default initialization.

        Dimensions are 0 until model is lazily loaded on first embed().
        """
        provider = LocalEmbedding()
        assert provider.get_dimensions() == 0
        assert provider.model_name == "all-MiniLM-L6-v2"

    def test_init_custom_model(self):
        """Test custom model name."""
        provider = LocalEmbedding(model_name="custom-model")
        assert provider.model_name == "custom-model"

    def test_get_config(self):
        """Test config returns metadata."""
        provider = LocalEmbedding()
        config = provider.get_config()
        assert config["provider"] == "LocalEmbedding"
        assert config["model"] == "all-MiniLM-L6-v2"

    def test_embed_without_sentence_transformers(self):
        """Test that ImportError is raised when sentence-transformers not installed."""
        provider = LocalEmbedding()
        with patch.dict('sys.modules', {'sentence_transformers': None}):
            with pytest.raises(ImportError, match="sentence-transformers"):
                provider._load_model()

    @skipif_no_local
    @pytest.mark.asyncio
    async def test_embed_real_model(self):
        """Test actual embedding with sentence-transformers model."""
        provider = LocalEmbedding()
        result = await provider.embed("Hello, world!")
        assert len(result.vector) == 384
        assert result.dimensions == 384
        assert result.model == "all-MiniLM-L6-v2"
        assert result.provider == "local"
        # Vector should be normalized (L2 norm ≈ 1.0)
        import math
        norm = math.sqrt(sum(v * v for v in result.vector))
        assert abs(norm - 1.0) < 0.01

    @skipif_no_local
    @pytest.mark.asyncio
    async def test_embed_batch_real(self):
        """Test batch embedding with multiple texts."""
        provider = LocalEmbedding()
        texts = ["First sentence.", "Second sentence about AI.", "Third."]
        results = await provider.embed_batch(texts)
        assert len(results) == 3
        for r in results:
            assert len(r.vector) == 384
            assert r.dimensions == 384
        # Similar sentences should have higher cosine similarity
        sim = provider.cosine_similarity(results[0].vector, results[1].vector)
        assert 0.0 <= sim <= 1.0

    @skipif_no_local
    @pytest.mark.asyncio
    async def test_embed_empty_string(self):
        """Test embedding an empty string produces a non-zero vector."""
        provider = LocalEmbedding()
        result = await provider.embed("")
        assert len(result.vector) == 384
        # Even empty strings should produce non-zero vectors
        assert any(abs(v) > 0.01 for v in result.vector[:10])


# ── Helper ──


class _MockProvider(EmbeddingProvider):
    """Minimal mock provider for testing base class."""

    async def embed(self, text: str) -> EmbeddingResult:
        return EmbeddingResult(
            vector=[0.1, 0.2],
            dimensions=2,
            model="mock",
            provider="mock",
        )

    async def embed_batch(self, texts: list[str], **kwargs) -> list[EmbeddingResult]:
        return [
            EmbeddingResult(vector=[0.1, 0.2], dimensions=2, model="mock", provider="mock")
            for _ in texts
        ]

    def get_dimensions(self) -> int:
        return 2


def _create_mock_provider() -> EmbeddingProvider:
    """Create a minimal mock provider."""
    return _MockProvider()

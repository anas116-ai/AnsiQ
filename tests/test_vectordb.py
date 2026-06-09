"""Tests for the Vector Database module — ChromaDB provider and base."""

from __future__ import annotations

import pytest

from ansiq.vectordb.base import SearchResult, VectorDBProvider

try:
    import chromadb  # noqa: F401
    _HAS_CHROMADB = True
except ImportError:
    _HAS_CHROMADB = False

skipif_no_chromadb = pytest.mark.skipif(
    not _HAS_CHROMADB,
    reason="chromadb not installed; install with: pip install chromadb",
)


class TestSearchResult:
    """Tests for SearchResult data class."""

    def test_create_result(self):
        r = SearchResult(id="doc1", score=0.95, payload={"text": "Hello"})
        assert r.id == "doc1"
        assert r.score == 0.95
        assert r.payload["text"] == "Hello"

    def test_repr(self):
        r = SearchResult(id="test", score=0.85)
        rep = repr(r)
        assert "test" in rep
        assert "0.85" in rep

    def test_default_payload(self):
        r = SearchResult(id="x", score=0.5)
        assert r.payload == {}


@skipif_no_chromadb
class TestChromaDBProvider:
    """Tests for ChromaDB provider — each test gets an isolated collection."""

    @pytest.fixture(autouse=True)
    async def db(self, request):
        """Create an isolated ephemeral ChromaDB provider with unique collection per test."""
        from ansiq.vectordb.chroma_provider import ChromaDBProvider
        provider = ChromaDBProvider(
            collection_name=f"test_{request.node.name}",
            persist_path=None,
        )
        return provider

    @pytest.mark.asyncio
    async def test_add_and_search(self, db):
        vector = [0.1, 0.2, 0.3, 0.4]
        added = await db.add("doc1", vector, {"text": "Hello world"})
        assert added is True

        results = await db.search([0.1, 0.2, 0.3, 0.4], top_k=5)
        assert len(results) >= 1
        assert results[0].id == "doc1"
        assert results[0].score > 0.9

    @pytest.mark.asyncio
    async def test_add_batch(self, db):
        vectors = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
        ]
        ids = ["v1", "v2"]
        payloads = [{"text": "Doc A"}, {"text": "Doc B"}]
        count = await db.add_batch(ids, vectors, payloads)
        assert count == 2

        results = await db.search([1.0, 0.0, 0.0, 0.0], top_k=5)
        assert len(results) >= 1
        assert results[0].id == "v1"

    @pytest.mark.asyncio
    async def test_search_empty_db(self, db):
        results = await db.search([0.1, 0.2, 0.3, 0.4], top_k=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_delete(self, db):
        await db.add("doc1", [0.1, 0.2, 0.3, 0.4])
        assert await db.count() == 1
        assert await db.delete("doc1") is True
        assert await db.count() == 0

    @pytest.mark.asyncio
    async def test_delete_batch(self, db):
        await db.add_batch(["a", "b", "c"], [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
        ])
        count = await db.delete_batch(["a", "c"])
        assert count == 2
        assert await db.count() == 1

    @pytest.mark.asyncio
    async def test_clear(self, db):
        await db.add("doc1", [0.1, 0.2, 0.3, 0.4])
        await db.add("doc2", [0.5, 0.6, 0.7, 0.8])
        assert await db.count() == 2
        await db.clear()
        assert await db.count() == 0

    @pytest.mark.asyncio
    async def test_similarity_ranking(self, db):
        vectors = [
            [1.0, 0.0, 0.0, 0.0],
            [0.8, 0.2, 0.0, 0.0],
            [0.5, 0.5, 0.0, 0.0],
        ]
        await db.add_batch(["exact", "close", "far"], vectors)

        results = await db.search([1.0, 0.0, 0.0, 0.0], top_k=3)
        assert len(results) == 3
        assert results[0].id == "exact"
        assert results[0].score >= results[1].score >= results[2].score


class TestVectorDBBase:
    """Tests for the base class."""

    def test_cosine_similarity(self):
        """Test cosine similarity utility."""
        provider = _MockProvider()
        sim = provider.cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        assert sim == 1.0

    def test_cosine_similarity_zero(self):
        provider = _MockProvider()
        sim = provider.cosine_similarity([1.0, 0.0, 0.0], [0.0, 1.0, 0.0])
        assert sim == 0.0


class _MockProvider(VectorDBProvider):
    """Minimal mock for testing base class."""
    async def add(self, id, vector, payload=None):
        return True
    async def add_batch(self, ids, vectors, payloads=None):
        return len(ids)
    async def search(self, vector, top_k=10, filter=None):
        return []
    async def delete(self, id):
        return True
    async def delete_batch(self, ids):
        return len(ids)
    async def count(self):
        return 0
    async def clear(self):
        pass

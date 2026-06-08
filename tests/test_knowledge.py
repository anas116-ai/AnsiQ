"""Tests for the Knowledge/RAG system."""

from __future__ import annotations

from ansiq.knowledge.engine import RAGEngine
from ansiq.knowledge.source import FileSource, TextSource, URLSource
from ansiq.knowledge.store import VectorKnowledgeStore


class TestKnowledgeSource:
    def test_text_source(self):
        """Test TextSource loads text content."""
        source = TextSource(name="test", text="Hello world")
        import asyncio
        content = asyncio.run(source.load())
        assert content == "Hello world"

    def test_text_source_chunks(self):
        """Test text source chunking."""
        source = TextSource(name="test", text="word " * 1000)
        import asyncio
        chunks = asyncio.run(source.get_chunks(chunk_size=100, overlap=10))
        assert len(chunks) >= 1
        assert chunks[0]["source"] == "test"
        assert "content_hash" in chunks[0]

    def test_file_source_nonexistent(self):
        """Test FileSource with non-existent file."""
        source = FileSource(name="missing", file_path="/nonexistent/file.txt")
        import asyncio
        content = asyncio.run(source.load())
        assert content == ""

    def test_url_source_invalid(self):
        """Test URLSource gracefully handles invalid URLs."""
        source = URLSource(name="bad_url", url="https://nonexistent.example.com/test")
        import asyncio
        content = asyncio.run(source.load())
        assert content == ""  # Should not raise

    def test_source_id(self):
        """Test getting a unique source ID."""
        source = TextSource(name="test", text="data")
        sid = source.get_source_id()
        assert len(sid) == 12


class TestVectorKnowledgeStore:
    def test_empty_store(self, tmp_path):
        """Test store with no chunks."""
        store = VectorKnowledgeStore(store_path=tmp_path / "store.json")
        results = store.search("test")
        assert results == []

    def test_add_and_search(self, tmp_path):
        """Test adding chunks and searching."""
        store = VectorKnowledgeStore(store_path=tmp_path / "store.json")
        store.add_chunks([
            {"text": "Machine learning is a subset of artificial intelligence", "source": "doc1"},
            {"text": "Python is a programming language", "source": "doc2"},
            {"text": "Neural networks are used in deep learning", "source": "doc3"},
        ])
        results = store.search("machine learning", top_k=2)
        assert len(results) > 0

    def test_keyword_search_fallback(self, tmp_path):
        """Test fallback keyword search."""
        store = VectorKnowledgeStore(store_path=tmp_path / "store.json")
        store.add_chunks([
            {"text": "Unique term xyz123abc", "source": "doc"},
        ])
        results = store.search("xyz123abc", top_k=5)
        assert len(results) > 0

    def test_get_formatted_context(self, tmp_path):
        """Test formatted context for prompts."""
        store = VectorKnowledgeStore(store_path=tmp_path / "store.json")
        store.add_chunks([
            {"text": "Important data here", "source": "ref"},
        ])
        context = store.get_formatted_context("data")
        assert isinstance(context, str)

    def test_count_chunks(self, tmp_path):
        """Test counting chunks."""
        store = VectorKnowledgeStore(store_path=tmp_path / "store.json")
        assert store.count_chunks() == 0
        store.add_chunks([{"text": "Test", "source": "a"}])
        assert store.count_chunks() == 1

    def test_clear(self, tmp_path):
        """Test clearing the store."""
        store = VectorKnowledgeStore(store_path=tmp_path / "store.json")
        store.add_chunks([{"text": "Test", "source": "a"}])
        store.clear()
        assert store.count_chunks() == 0

    def test_get_stats(self, tmp_path):
        """Test getting store stats."""
        store = VectorKnowledgeStore(store_path=tmp_path / "store.json")
        store.add_chunks([
            {"text": "Data A", "source": "src1"},
            {"text": "Data B", "source": "src1"},
        ])
        stats = store.get_stats()
        assert stats["total_chunks"] == 2


class TestRAGEngine:
    def test_create_engine(self, tmp_path):
        """Test creating a RAG engine."""
        store = VectorKnowledgeStore(store_path=tmp_path / "rag.json")
        engine = RAGEngine(store=store)
        assert len(engine.get_stats()["sources"]) == 0

    def test_add_source(self, tmp_path):
        """Test adding a text source to the engine."""
        store = VectorKnowledgeStore(store_path=tmp_path / "rag.json")
        engine = RAGEngine(store=store)
        source = TextSource(name="test_doc", text="This is test content for RAG")
        import asyncio

        result = asyncio.run(engine.add_source(source))
        assert result is True
        assert "test_doc" in engine.get_stats()["sources"]

    def test_query(self, tmp_path):
        """Test querying the RAG engine."""
        store = VectorKnowledgeStore(store_path=tmp_path / "rag.json")
        engine = RAGEngine(store=store)
        source = TextSource(name="doc", text="Machine learning concepts explained")
        import asyncio
        asyncio.run(engine.add_source(source))
        results = engine.query("machine learning")
        assert isinstance(results, list)

    def test_get_context(self, tmp_path):
        """Test getting formatted context."""
        store = VectorKnowledgeStore(store_path=tmp_path / "rag.json")
        engine = RAGEngine(store=store)
        source = TextSource(name="ref", text="Key information for queries")
        import asyncio
        asyncio.run(engine.add_source(source))
        context = engine.get_context("queries")
        assert isinstance(context, str)

    def test_clear_engine(self, tmp_path):
        """Test clearing the engine."""
        store = VectorKnowledgeStore(store_path=tmp_path / "rag.json")
        engine = RAGEngine(store=store)
        import asyncio
        asyncio.run(engine.clear())
        assert len(engine.get_stats()["sources"]) == 0

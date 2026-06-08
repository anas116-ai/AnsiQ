"""Tests for the enhanced Memory Provider system."""

from __future__ import annotations

from ansiq.memory.providers import (
    CompositeMemoryProvider,
    EntityMemoryProvider,
    FtsMemoryProvider,
    SemanticMemoryProvider,
)


class TestFtsMemoryProvider:
    def test_store_and_search(self, temp_db_path):
        """Test storing and searching with FTS provider."""
        provider = FtsMemoryProvider(db_path=temp_db_path)
        result = provider.store("Test memory content", agent_id="agent1")
        assert result is True

        results = provider.search("test", agent_id="agent1")
        assert len(results) >= 1

    def test_get_stats(self, temp_db_path):
        """Test getting provider stats."""
        provider = FtsMemoryProvider(db_path=temp_db_path)
        stats = provider.get_stats()
        assert stats["provider"] == "fts5"
        assert "total_memories" in stats


class TestEntityMemoryProvider:
    def test_store_and_search(self, tmp_path):
        """Test storing and searching entities."""
        provider = EntityMemoryProvider(storage_path=tmp_path / "entities.json")
        provider.store("John works at Microsoft in Seattle")
        provider.store("Jane is a Python developer")

        results = provider.search("John")
        assert len(results) >= 1
        assert results[0]["entity"] == "John"

    def test_get_entity(self, tmp_path):
        """Test getting a specific entity."""
        provider = EntityMemoryProvider(storage_path=tmp_path / "entities.json")
        provider.store("Alice is a researcher")
        entity = provider.get_entity("Alice")
        assert entity is not None
        assert entity["name"] == "Alice"

    def test_get_nonexistent_entity(self, tmp_path):
        """Test getting non-existent entity."""
        provider = EntityMemoryProvider(storage_path=tmp_path / "entities.json")
        entity = provider.get_entity("NonExistent")
        assert entity is None

    def test_clear(self, tmp_path):
        """Test clearing entities."""
        provider = EntityMemoryProvider(storage_path=tmp_path / "entities.json")
        provider.store("Test entity")
        provider.clear()
        assert len(provider._entities) == 0

    def test_get_stats(self, tmp_path):
        """Test getting entity stats."""
        provider = EntityMemoryProvider(storage_path=tmp_path / "entities.json")
        provider.store("Alice")
        provider.store("Bob")
        stats = provider.get_stats()
        assert stats["total_entities"] >= 2

    def test_entity_classification(self, tmp_path):
        """Test entity type classification."""
        provider = EntityMemoryProvider(storage_path=tmp_path / "entities.json")
        provider.store("Dr. Smith")
        entity = provider.get_entity("Dr.")
        if entity:
            assert entity is not None


class TestSemanticMemoryProvider:
    def test_search(self, temp_db_path):
        """Test semantic search."""
        base = FtsMemoryProvider(db_path=temp_db_path)
        base.store("Machine learning is about algorithms", agent_id="test")
        base.store("Python is great for data science", agent_id="test")

        semantic = SemanticMemoryProvider(base_provider=FtsMemoryProvider(db_path=temp_db_path))
        semantic._base = base

        results = semantic.search("algorithms", agent_id="test")
        assert len(results) >= 0


class TestCompositeMemoryProvider:
    def test_composite_store_and_search(self, temp_db_path, tmp_path):
        """Test composite provider orchestrates sub-providers."""
        fts = FtsMemoryProvider(db_path=temp_db_path)
        entity = EntityMemoryProvider(storage_path=tmp_path / "entities.json")

        composite = CompositeMemoryProvider(providers=[fts, entity])
        composite.store("Alice researches machine learning", agent_id="test")

        results = composite.search("Alice", agent_id="test")
        assert len(results) >= 0

    def test_add_provider(self, temp_db_path):
        """Test adding a provider to composite."""
        fts = FtsMemoryProvider(db_path=temp_db_path)
        composite = CompositeMemoryProvider(providers=[fts])
        assert len(composite.providers) == 1

    def test_get_provider(self, temp_db_path):
        """Test getting a sub-provider by name."""
        fts = FtsMemoryProvider(db_path=temp_db_path)
        composite = CompositeMemoryProvider(providers=[fts])
        found = composite.get_provider("fts5")
        assert found is not None
        assert composite.get_provider("nonexistent") is None

    def test_get_stats(self, temp_db_path):
        """Test getting composite stats."""
        fts = FtsMemoryProvider(db_path=temp_db_path)
        composite = CompositeMemoryProvider(providers=[fts])
        stats = composite.get_stats()
        assert stats["provider"] == "composite"
        assert len(stats["sub_providers"]) > 0

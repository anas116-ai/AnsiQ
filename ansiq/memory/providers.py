"""Memory Provider abstraction — pluggable memory backends.

Inspired by Hermes Agent's multi-provider architecture:
- Ft5MemoryProvider: local SQLite FTS5 (default)
- EntityMemoryProvider: tracks people, concepts, locations
- SemanticMemoryProvider: embedding-based semantic recall
- CompositeMemoryProvider: orchestrates multiple providers
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections import Counter
from pathlib import Path
from typing import Any

from ansiq.memory.fts_store import FTSMemoryStore

logger = logging.getLogger(__name__)


class MemoryProvider(ABC):
    """Abstract base for all memory providers.

    Each provider implements a different strategy for storing
    and retrieving memories. Agents can use multiple providers
    simultaneously via CompositeMemoryProvider.
    """

    name: str = "base"

    @abstractmethod
    def store(
        self,
        content: str,
        agent_id: str = "default",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Store a memory."""
        ...

    @abstractmethod
    def search(
        self,
        query: str,
        agent_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search memories."""
        ...

    @abstractmethod
    def get_relevant_context(
        self,
        query: str = "",
        agent_id: str = "default",
        limit: int = 5,
    ) -> str:
        """Get formatted context string."""
        ...

    @abstractmethod
    def get_stats(self) -> dict[str, Any]:
        """Get provider statistics."""
        ...


class FtsMemoryProvider(MemoryProvider):
    """FTS5-based memory provider using local SQLite.

    Default provider. Fast full-text search, no external dependencies.
    """

    name = "fts5"

    def __init__(self, db_path: Path | str | None = None):
        self._store = FTSMemoryStore(db_path=db_path)

    def store(
        self,
        content: str,
        agent_id: str = "default",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        try:
            self._store.store(
                content=content,
                agent_id=agent_id,
                tags=tags,
                metadata=metadata,
            )
            return True
        except Exception as e:
            logger.error("FTS store failed: %s", e)
            return False

    def search(
        self,
        query: str,
        agent_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return self._store.search(query, agent_id=agent_id, limit=limit)

    def get_relevant_context(
        self,
        query: str = "",
        agent_id: str = "default",
        limit: int = 5,
    ) -> str:
        return self._store.get_relevant_context(query, agent_id, limit)

    def get_stats(self) -> dict[str, Any]:
        return {
            "provider": "fts5",
            "total_memories": self._store.count(),
            "db_path": str(self._store.db_path),
        }


class EntityMemoryProvider(MemoryProvider):
    """Tracks entities (people, concepts, locations) across conversations.

    Builds a knowledge graph of entities encountered during
    agent interactions. Inspired by CrewAI's Entity Memory.
    """

    name = "entity"

    def __init__(self, storage_path: Path | str | None = None):
        self.storage_path = Path(storage_path or Path.home() / ".ansiq" / "entities.json")
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._entities: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self.storage_path.exists():
            try:
                self._entities = json.loads(self.storage_path.read_text())
            except Exception:
                self._entities = {}

    def _save(self) -> None:
        try:
            self.storage_path.write_text(json.dumps(self._entities, indent=2))
        except Exception as e:
            logger.warning("Failed to save entities: %s", e)

    def store(
        self,
        content: str,
        agent_id: str = "default",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Extract and store entities from content."""
        import re

        # Simple entity extraction: look for capitalized words and common patterns
        words = re.findall(r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\b", content)
        for word in words:
            if len(word) < 2:
                continue
            entity_type = self._classify_entity(word, content)

            if word not in self._entities:
                self._entities[word] = {
                    "name": word,
                    "type": entity_type,
                    "first_seen": None,
                    "last_seen": None,
                    "mentions": 0,
                    "contexts": [],
                    "relations": {},
                }

            entity = self._entities[word]
            entity["mentions"] += 1
            entity["contexts"].append(content[:200])

            # Keep only last 10 contexts
            if len(entity["contexts"]) > 10:
                entity["contexts"] = entity["contexts"][-10:]

        self._save()
        return True

    def _classify_entity(self, name: str, context: str) -> str:
        """Classify an entity based on context clues."""
        context_lower = context.lower()
        if any(word in context_lower for word in ["person", "mr", "ms", "dr", "professor", "ceo"]):
            return "person"
        if any(word in context_lower for word in ["company", "inc", "corp", "ltd", "organization"]):
            return "organization"
        if any(
            word in context_lower for word in ["city", "country", "place", "region", "location"]
        ):
            return "location"
        if any(
            word in context_lower
            for word in ["technology", "framework", "language", "tool", "library"]
        ):
            return "technology"
        return "concept"

    def search(
        self,
        query: str,
        agent_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        query_lower = query.lower()
        results = []
        for name, entity in self._entities.items():
            if query_lower in name.lower() or query_lower in str(entity.get("contexts", [])):
                results.append(
                    {
                        "entity": name,
                        "type": entity.get("type"),
                        "mentions": entity.get("mentions", 0),
                        "last_context": entity["contexts"][-1] if entity.get("contexts") else "",
                    }
                )
        return sorted(results, key=lambda x: x["mentions"], reverse=True)[:limit]

    def get_relevant_context(
        self,
        query: str = "",
        agent_id: str = "default",
        limit: int = 5,
    ) -> str:
        results = self.search(query, limit=limit)
        if not results:
            return ""

        parts = ["## Known Entities\n"]
        for r in results:
            parts.append(f"- {r['entity']} ({r['type']}, mentioned {r['mentions']}x)")
        return "\n".join(parts)

    def get_entity(self, name: str) -> dict[str, Any] | None:
        """Get details about a specific entity."""
        return self._entities.get(name)

    def get_stats(self) -> dict[str, Any]:
        return {
            "provider": "entity",
            "total_entities": len(self._entities),
            "types": dict(Counter(e.get("type", "unknown") for e in self._entities.values())),
        }

    def clear(self) -> None:
        """Clear all stored entities."""
        self._entities.clear()
        self._save()


class SemanticMemoryProvider(MemoryProvider):
    """Semantic memory — retrieves memories by meaning, not exact keywords.

    Uses simple word-vector similarity for semantic matching.
    For production, this would use embeddings from an actual embedding model.
    """

    name = "semantic"

    def __init__(self, base_provider: FtsMemoryProvider | None = None):
        self._base = base_provider or FtsMemoryProvider()

    def store(
        self,
        content: str,
        agent_id: str = "default",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        return self._base.store(content, agent_id, tags, metadata)

    def search(
        self,
        query: str,
        agent_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        # Get FTS5 results and enrich with semantic scoring
        base_results = self._base.search(query, agent_id, limit * 2)

        if not base_results:
            return []

        # Score results by word overlap (simple semantic proxy)
        query_words = set(query.lower().split())
        scored = []
        for r in base_results:
            content_words = set(r.get("content", "").lower().split())
            overlap = len(query_words & content_words)
            score = overlap / max(len(query_words), 1)
            scored.append((score, r))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [{**r, "semantic_score": round(score, 4)} for score, r in scored[:limit]]

    def get_relevant_context(
        self,
        query: str = "",
        agent_id: str = "default",
        limit: int = 5,
    ) -> str:
        return self._base.get_relevant_context(query, agent_id, limit)

    def get_stats(self) -> dict[str, Any]:
        stats = self._base.get_stats()
        stats["provider"] = "semantic"
        return stats


class CompositeMemoryProvider(MemoryProvider):
    """Orchestrates multiple memory providers together.

    Queries all providers and merges results with deduplication.
    This is the primary memory interface agents should use.
    """

    name = "composite"

    def __init__(self, providers: list[MemoryProvider] | None = None):
        self.providers: list[MemoryProvider] = providers or [
            FtsMemoryProvider(),
            EntityMemoryProvider(),
            SemanticMemoryProvider(),
        ]

    def add_provider(self, provider: MemoryProvider) -> None:
        """Add a memory provider to the composite."""
        self.providers.append(provider)

    def store(
        self,
        content: str,
        agent_id: str = "default",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        success = True
        for provider in self.providers:
            if not provider.store(content, agent_id, tags, metadata):
                success = False
        return success

    def search(
        self,
        query: str,
        agent_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        all_results: list[dict[str, Any]] = []
        seen: set[str] = set()

        for provider in self.providers:
            results = provider.search(query, agent_id, limit)
            for r in results:
                # Deduplicate by content
                content = r.get("content", "") or r.get("entity", "") or r.get("name", "")
                key = str(hash(content[:100]))
                if key not in seen:
                    seen.add(key)
                    r["_provider"] = provider.name
                    all_results.append(r)

        # Sort by relevance (provider priority)
        return all_results[:limit]

    def get_relevant_context(
        self,
        query: str = "",
        agent_id: str = "default",
        limit: int = 5,
    ) -> str:
        memories = self.search(query, agent_id, limit)
        if not memories:
            return ""

        parts = ["## Memory Context\n"]
        for mem in memories:
            source_type = mem.get("entity", mem.get("content", ""))[:100]
            provider = mem.get("_provider", "unknown")
            parts.append(f"- [{provider}] {source_type}")
        return "\n".join(parts)

    def get_stats(self) -> dict[str, Any]:
        return {
            "provider": "composite",
            "sub_providers": [p.get_stats() for p in self.providers],
        }

    def get_provider(self, name: str) -> MemoryProvider | None:
        """Get a specific sub-provider by name."""
        for p in self.providers:
            if p.name == name:
                return p
        return None

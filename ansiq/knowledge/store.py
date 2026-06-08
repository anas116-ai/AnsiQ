"""Vector Knowledge Store — stores and retrieves knowledge chunks.

Uses real vector embeddings for semantic search alongside TF-IDF fallback.
Supports multiple embedding backends (OpenAI, local sentence-transformers)
and optional vector database backends (ChromaDB, FAISS, etc.).

The store is persistent (JSON on disk) and uses numpy for efficient
cosine similarity computation on dense vectors.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_STORE_PATH = Path.home() / ".ansiq" / "knowledge_store.json"


class VectorKnowledgeStore:
    """A vector store for knowledge chunks with real embedding search.

    Features:
    - Semantic search via vector embeddings (cosine similarity with numpy)
    - Optional VectorDB backend (ChromaDB) for production-grade search
    - TF-IDF fallback when embeddings are unavailable
    - Persistent storage (JSON on disk)
    - Automatic embedding generation on add_chunks()

    Example:
        from ansiq.vectordb.chroma_provider import ChromaDBProvider

        store = VectorKnowledgeStore(
            embedding_provider=OpenAIEmbedding(),
            vector_db=ChromaDBProvider(),
        )
        await store.add_chunks_async([{"text": "AI concepts", "source": "doc"}])
        results = store.search("machine learning")
    """

    def __init__(
        self,
        store_path: Path | str | None = None,
        embedding_provider: Any | None = None,
        vector_db: Any | None = None,
    ):
        self.store_path = Path(store_path or _DEFAULT_STORE_PATH)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self._embedding_provider = embedding_provider
        self._vector_db = vector_db
        self._chunks: list[dict[str, Any]] = []
        self._embeddings: list[list[float]] = []  # parallel to _chunks
        self._vocabulary: dict[str, int] = {}
        self._doc_freq: Counter = Counter()
        self._loaded = False

    def _load(self) -> None:
        """Load stored chunks and embeddings from disk."""
        if self._loaded:
            return
        if self.store_path.exists():
            try:
                data = json.loads(self.store_path.read_text())
                self._chunks = data.get("chunks", [])
                self._embeddings = data.get("embeddings", [])
                self._vocabulary = data.get("vocabulary", {})
                self._doc_freq = Counter(data.get("doc_freq", {}))
            except Exception as e:
                logger.warning("Failed to load knowledge store: %s", e)
        self._loaded = True

    def _save(self) -> None:
        """Save chunks and embeddings to disk."""
        try:
            data = {
                "chunks": self._chunks,
                "embeddings": self._embeddings,
                "vocabulary": self._vocabulary,
                "doc_freq": dict(self._doc_freq),
            }
            self.store_path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.warning("Failed to save knowledge store: %s", e)

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text into lowercase words."""
        return re.findall(r"\b[a-zA-Z0-9_]+\b", text.lower())

    def _compute_tf_vector(self, tokens: list[str]) -> dict[int, float]:
        """Compute TF-IDF vector for a set of tokens."""
        term_freq = Counter(tokens)
        max_freq = max(term_freq.values()) if term_freq else 1

        vector: dict[int, float] = {}
        for term, freq in term_freq.items():
            if term in self._vocabulary:
                idx = self._vocabulary[term]
                tf = freq / max_freq
                n = len(self._chunks)
                df = self._doc_freq.get(term, 1)
                idf = math.log((n + 1) / (df + 1)) + 1
                vector[idx] = tf * idf
        return vector

    def _cosine_similarity_sparse(self, vec1: dict[int, float], vec2: dict[int, float]) -> float:
        """Compute cosine similarity between two sparse TF-IDF vectors."""
        intersection = set(vec1.keys()) & set(vec2.keys())
        dot_product = sum(vec1[i] * vec2[i] for i in intersection)
        norm1 = math.sqrt(sum(v * v for v in vec1.values()))
        norm2 = math.sqrt(sum(v * v for v in vec2.values()))
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot_product / (norm1 * norm2)

    def _cosine_similarity_dense(self, vec1: list[float], vec2: list[float]) -> float:
        """Compute cosine similarity between two dense vectors using numpy."""
        try:
            import numpy as np

            v1 = np.array(vec1, dtype=np.float32)
            v2 = np.array(vec2, dtype=np.float32)
            norm1 = np.linalg.norm(v1)
            norm2 = np.linalg.norm(v2)
            if norm1 == 0 or norm2 == 0:
                return 0.0
            return float(np.dot(v1, v2) / (norm1 * norm2))
        except ImportError:
            dot = sum(a * b for a, b in zip(vec1, vec2, strict=False))
            norm1 = math.sqrt(sum(a * a for a in vec1))
            norm2 = math.sqrt(sum(b * b for b in vec2))
            if norm1 == 0 or norm2 == 0:
                return 0.0
            return dot / (norm1 * norm2)

    def _get_chunk_id(self, chunk: dict[str, Any]) -> str:
        """Get a unique ID for a chunk based on content_hash or index."""
        return chunk.get("content_hash", f"chunk_{id(chunk)}")

    async def _embed_chunk_async(self, text: str) -> list[float] | None:
        """Async: generate embedding vector for a text chunk."""
        if not self._embedding_provider or not text.strip():
            return None
        try:
            result = await self._embedding_provider.embed(text)
            return result.vector
        except Exception as e:
            logger.debug("Failed to generate embedding: %s", e)
            return None

    async def add_chunks_async(self, chunks: list[dict[str, Any]]) -> int:
        """Async: add chunks with automatic embedding generation.

        If a VectorDB is configured, vectors are stored there for
        production-grade search. Otherwise they're stored in the local
        JSON store.

        Returns count of new chunks added.
        """
        self._load()

        added = 0
        batch_ids: list[str] = []
        batch_vectors: list[list[float]] = []
        batch_payloads: list[dict[str, Any]] = []

        for chunk in chunks:
            text = chunk.get("text", "")
            if not text:
                continue

            content_hash = chunk.get("content_hash", "")
            if content_hash and any(c.get("content_hash") == content_hash for c in self._chunks):
                continue

            # Update vocabulary (for TF-IDF fallback)
            tokens = self._tokenize(text)
            for token in set(tokens):
                if token not in self._vocabulary:
                    self._vocabulary[token] = len(self._vocabulary)
                self._doc_freq[token] += 1

            # Generate embedding vector
            embedding = await self._embed_chunk_async(text)

            # Store locally
            self._chunks.append(chunk)
            self._embeddings.append(embedding if embedding else [])
            added += 1

            # Store in VectorDB if configured
            if embedding and self._vector_db:
                chunk_id = self._get_chunk_id(chunk)
                batch_ids.append(chunk_id)
                batch_vectors.append(embedding)
                payload = {
                    "text": text,
                    "source": chunk.get("source", ""),
                    "chunk_index": chunk.get("chunk_index", 0),
                    **chunk.get("metadata", {}),
                }
                batch_payloads.append(payload)

        # Batch insert into VectorDB
        if batch_ids and self._vector_db:
            try:
                inserted = await self._vector_db.add_batch(batch_ids, batch_vectors, batch_payloads)
                logger.debug("Inserted %d vectors into VectorDB", inserted)
            except Exception as e:
                logger.warning("VectorDB batch insert failed: %s", e)

        if added > 0:
            self._save()

        logger.debug("Added %d knowledge chunks (total: %d)", added, len(self._chunks))
        return added

    def add_chunks(self, chunks: list[dict[str, Any]]) -> int:
        """Sync: add knowledge chunks (skips embedding, builds TF-IDF)."""
        self._load()
        added = 0
        for chunk in chunks:
            text = chunk.get("text", "")
            if not text:
                continue
            content_hash = chunk.get("content_hash", "")
            if content_hash and any(c.get("content_hash") == content_hash for c in self._chunks):
                continue
            tokens = self._tokenize(text)
            for token in set(tokens):
                if token not in self._vocabulary:
                    self._vocabulary[token] = len(self._vocabulary)
                self._doc_freq[token] += 1
            self._chunks.append(chunk)
            self._embeddings.append([])
            added += 1
        if added > 0:
            self._save()
        logger.debug("Added %d knowledge chunks (total: %d)", added, len(self._chunks))
        return added

    async def generate_missing_embeddings(self) -> int:
        """Generate embeddings for chunks that don't have them yet.

        Returns count of embeddings generated.
        """
        if not self._embedding_provider:
            logger.warning("No embedding provider configured, skipping")
            return 0

        self._load()
        generated = 0
        texts_to_embed: list[tuple[int, str]] = []

        for i, (chunk, emb) in enumerate(zip(self._chunks, self._embeddings, strict=False)):
            if not emb and chunk.get("text", "").strip():
                texts_to_embed.append((i, chunk["text"]))

        if not texts_to_embed:
            return 0

        texts = [t[1] for t in texts_to_embed]
        try:
            results = await self._embedding_provider.embed_batch(texts)
            for (idx, _), result in zip(texts_to_embed, results, strict=False):
                self._embeddings[idx] = result.vector
                generated += 1
        except Exception as e:
            logger.error("Failed to generate batch embeddings: %s", e)

        if generated > 0:
            self._save()
        logger.info("Generated %d missing embeddings", generated)
        return generated

    def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.05,
        use_embeddings: bool = True,
    ) -> list[dict[str, Any]]:
        """Search for relevant chunks.

        Uses VectorDB if available, then vector embeddings, then TF-IDF,
        then keyword matching as fallback.

        Args:
            query: Search query text.
            top_k: Maximum number of results.
            min_score: Minimum similarity score threshold.
            use_embeddings: If True, prefer vector search over TF-IDF.

        Returns:
            List of chunks with 'score' field added.
        """
        self._load()

        if not self._chunks or not query.strip():
            return []

        # Try VectorDB search first (if configured and embeddings exist)
        if use_embeddings and self._vector_db and self._embedding_provider:
            vectordb_results = self._vectordb_search(query, top_k, min_score)
            if vectordb_results:
                return vectordb_results

        # Try local vector search next
        has_embeddings = any(e for e in self._embeddings)
        if use_embeddings and has_embeddings and self._embedding_provider:
            vector_results = self._vector_search(query, top_k, min_score)
            if vector_results:
                return vector_results

        # Fallback to TF-IDF
        return self._tfidf_search(query, top_k, min_score)

    async def search_async(
        self,
        query: str,
        top_k: int = 5,
        use_vectordb: bool = True,
    ) -> list[dict[str, Any]]:
        """Async version of search — uses VectorDB for embedding-based search.

        This is the preferred method when a VectorDB is configured
        because it can generate the query embedding asynchronously.
        """
        self._load()

        if not self._chunks or not query.strip():
            return []

        if use_vectordb and self._vector_db and self._embedding_provider:
            try:
                result = await self._embedding_provider.embed(query)
                if result and any(result.vector):
                    vectordb_results = await self._vector_db.search(result.vector, top_k=top_k)
                    if vectordb_results:
                        # Map VectorDB results back to chunks
                        output = []
                        for vr in vectordb_results:
                            chunk = self._find_chunk_by_id(vr.id)
                            if chunk:
                                output.append(
                                    {**chunk, "score": vr.score, "search_type": "vectordb"}
                                )
                            else:
                                output.append(
                                    {
                                        "text": vr.payload.get("text", ""),
                                        "source": vr.payload.get("source", ""),
                                        "score": vr.score,
                                        "search_type": "vectordb",
                                    }
                                )
                            if len(output) >= top_k:
                                break
                        return output
            except Exception as e:
                logger.warning("VectorDB async search failed: %s", e)

        return self.search(query, top_k=top_k)

    def _find_chunk_by_id(self, chunk_id: str) -> dict[str, Any] | None:
        """Find a local chunk by its content_hash."""
        for chunk in self._chunks:
            if chunk.get("content_hash") == chunk_id:
                return chunk
        return None

    def _vectordb_search(
        self, query: str, top_k: int = 5, min_score: float = 0.05
    ) -> list[dict[str, Any]]:
        """Search using VectorDB (synchronous wrapper)."""
        try:
            import asyncio

            loop = asyncio.get_running_loop()
            future = asyncio.run_coroutine_threadsafe(self._embedding_provider.embed(query), loop)
            query_vec = future.result().vector
        except RuntimeError:
            return []
        except Exception:
            return []

        if not query_vec or not any(query_vec):
            return []

        try:
            import asyncio

            loop = asyncio.get_running_loop()
            future = asyncio.run_coroutine_threadsafe(
                self._vector_db.search(query_vec, top_k=top_k), loop
            )
            results = future.result()
        except Exception:
            return []

        output = []
        for vr in results:
            if vr.score >= min_score:
                chunk = self._find_chunk_by_id(vr.id)
                if chunk:
                    output.append({**chunk, "score": vr.score, "search_type": "vectordb"})
                else:
                    output.append(
                        {
                            "text": vr.payload.get("text", ""),
                            "source": vr.payload.get("source", ""),
                            "score": vr.score,
                            "search_type": "vectordb",
                        }
                    )
                if len(output) >= top_k:
                    break

        return output

    def _vector_search(
        self, query: str, top_k: int = 5, min_score: float = 0.05
    ) -> list[dict[str, Any]]:
        """Search using local vector embeddings."""
        try:
            import asyncio

            loop = asyncio.get_running_loop()
            future = asyncio.run_coroutine_threadsafe(self._embedding_provider.embed(query), loop)
            query_vec = future.result().vector
        except RuntimeError:
            logger.warning("No running event loop; falling back to TF-IDF search")
            return []
        except Exception as e:
            logger.warning("Vector search failed: %s", e)
            return []

        if not query_vec or not any(query_vec):
            return []

        scored: list[tuple[float, dict[str, Any]]] = []
        for i, chunk in enumerate(self._chunks):
            emb = self._embeddings[i]
            if not emb:
                continue
            score = self._cosine_similarity_dense(query_vec, emb)
            if score >= min_score:
                scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {**chunk, "score": round(score, 4), "search_type": "vector"}
            for score, chunk in scored[:top_k]
        ]

    def _tfidf_search(
        self, query: str, top_k: int = 5, min_score: float = 0.05
    ) -> list[dict[str, Any]]:
        """Search using TF-IDF cosine similarity."""
        query_tokens = self._tokenize(query)
        query_vec = self._compute_tf_vector(query_tokens)
        if not query_vec:
            return self._keyword_search(query, top_k)
        scored: list[tuple[float, dict[str, Any]]] = []
        for chunk in self._chunks:
            chunk_tokens = self._tokenize(chunk.get("text", ""))
            chunk_vec = self._compute_tf_vector(chunk_tokens)
            score = self._cosine_similarity_sparse(query_vec, chunk_vec)
            if score >= min_score:
                scored.append((score, chunk))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {**chunk, "score": round(score, 4), "search_type": "tfidf"}
            for score, chunk in scored[:top_k]
        ]

    def _keyword_search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Fallback keyword-based search."""
        query_terms = set(self._tokenize(query))
        if not query_terms:
            return []
        scored: list[tuple[int, dict[str, Any]]] = []
        for chunk in self._chunks:
            chunk_terms = set(self._tokenize(chunk.get("text", "")))
            matches = len(query_terms & chunk_terms)
            if matches > 0:
                scored.append((matches, chunk))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {**chunk, "score": round(matches / len(query_terms), 4), "search_type": "keyword"}
            for matches, chunk in scored[:top_k]
        ]

    def get_formatted_context(self, query: str, top_k: int = 3, max_chars: int = 2000) -> str:
        """Get formatted context string for LLM prompt injection."""
        results = self.search(query, top_k=top_k)
        if not results:
            return ""
        parts = ["## Relevant Knowledge\n"]
        char_count = 0
        for i, result in enumerate(results, 1):
            text = result.get("text", "")
            source = result.get("source", "unknown")
            score = result.get("score", 0)
            entry = f"\n[{i}] From '{source}' (relevance: {score:.2f}):\n{text}\n"
            char_count += len(entry)
            if char_count > max_chars:
                break
            parts.append(entry)
        return "".join(parts)

    def count_chunks(self) -> int:
        self._load()
        return len(self._chunks)

    def count_embedded(self) -> int:
        self._load()
        return sum(1 for e in self._embeddings if e)

    def clear(self) -> None:
        self._chunks.clear()
        self._embeddings.clear()
        self._vocabulary.clear()
        self._doc_freq.clear()
        self._save()
        logger.info("Knowledge store cleared")

    def get_stats(self) -> dict[str, Any]:
        self._load()
        return {
            "total_chunks": len(self._chunks),
            "embedded_chunks": self.count_embedded(),
            "vocabulary_size": len(self._vocabulary),
            "total_sources": len(set(c.get("source", "") for c in self._chunks)),
            "store_path": str(self.store_path),
            "vector_db": "configured" if self._vector_db else "not configured",
            "embedding_provider": (
                self._embedding_provider.get_config() if self._embedding_provider else None
            ),
        }

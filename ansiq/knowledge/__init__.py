"""Knowledge module — RAG system for attaching data to crews.

Agents can query knowledge sources (files, URLs, documents)
to augment their responses with relevant context.

Supports vector embeddings for semantic search:
    from ansiq.embeddings.openai_provider import OpenAIEmbedding

    store = VectorKnowledgeStore(embedding_provider=OpenAIEmbedding())
    engine = RAGEngine(store=store)
"""

from ansiq.knowledge.engine import RAGEngine
from ansiq.knowledge.source import (
    DirectorySource,
    FileSource,
    KnowledgeSource,
    TextSource,
    URLSource,
)
from ansiq.knowledge.store import VectorKnowledgeStore

__all__ = [
    "KnowledgeSource",
    "TextSource",
    "FileSource",
    "URLSource",
    "DirectorySource",
    "VectorKnowledgeStore",
    "RAGEngine",
]

"""Vector Database — pluggable backends for production-grade vector search.

Supports:
- ChromaDB: persistent, open-source vector database
- More backends can be added by extending VectorDBProvider
"""

from ansiq.vectordb.base import SearchResult, VectorDBProvider
from ansiq.vectordb.chroma_provider import ChromaDBProvider

__all__ = [
    "VectorDBProvider",
    "SearchResult",
    "ChromaDBProvider",
]

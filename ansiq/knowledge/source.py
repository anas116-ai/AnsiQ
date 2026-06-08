"""Knowledge sources — attach data to crews for RAG.

Supports text, files, URLs, and directories as knowledge sources.
Each source is processed, chunked, and indexed for retrieval.
"""

from __future__ import annotations

import hashlib
import logging
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class KnowledgeSource(ABC):
    """Base class for all knowledge sources.

    A knowledge source provides content that can be chunked,
    indexed, and retrieved by agents during task execution.
    """

    def __init__(self, name: str, metadata: dict[str, Any] | None = None):
        self.name = name
        self.metadata = metadata or {}
        self._content_hash: str | None = None

    @abstractmethod
    async def load(self) -> str:
        """Load and return the raw content from this source."""
        ...

    async def get_chunks(self, chunk_size: int = 500, overlap: int = 50) -> list[dict[str, Any]]:
        """Load content and split into overlapping chunks."""
        content = await self.load()
        if not content:
            return []

        chunks = []
        words = content.split()

        for i in range(0, len(words), chunk_size - overlap):
            chunk_words = words[i : i + chunk_size]
            if not chunk_words:
                continue
            chunk_text = " ".join(chunk_words)
            chunks.append(
                {
                    "text": chunk_text,
                    "source": self.name,
                    "chunk_index": len(chunks),
                    "content_hash": hashlib.md5(chunk_text.encode()).hexdigest(),
                    "metadata": self.metadata,
                }
            )

        return chunks

    def get_source_id(self) -> str:
        """Get a unique identifier for this source."""
        raw = f"{self.name}:{type(self).__name__}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]


class TextSource(KnowledgeSource):
    """A knowledge source from raw text."""

    def __init__(
        self,
        name: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ):
        super().__init__(name, metadata)
        self._text = text

    async def load(self) -> str:
        return self._text


class FileSource(KnowledgeSource):
    """A knowledge source from a file (txt, md, pdf, etc.)."""

    SUPPORTED_EXTENSIONS = {".txt", ".md", ".py", ".json", ".yaml", ".yml", ".csv", ".html", ".xml"}

    def __init__(
        self,
        name: str,
        file_path: str | Path,
        metadata: dict[str, Any] | None = None,
    ):
        super().__init__(name, metadata)
        self.file_path = Path(file_path)

    async def load(self) -> str:
        if not self.file_path.exists():
            logger.warning("Knowledge file not found: %s", self.file_path)
            return ""

        ext = self.file_path.suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            logger.warning("Unsupported file extension: %s", ext)
            return ""

        try:
            import aiofiles

            async with aiofiles.open(self.file_path, encoding="utf-8", errors="replace") as f:
                return await f.read()
        except Exception as e:
            logger.error("Failed to read file %s: %s", self.file_path, e)
            return ""


class URLSource(KnowledgeSource):
    """A knowledge source from a URL."""

    def __init__(
        self,
        name: str,
        url: str,
        metadata: dict[str, Any] | None = None,
    ):
        super().__init__(name, metadata)
        self.url = url

    async def load(self) -> str:
        client = None
        try:
            import httpx

            # Short connect timeout so unreachable hosts fail fast instead of
            # stalling on DNS for the full 30s. 30s still allowed for read.
            timeout = httpx.Timeout(connect=3.0, read=30.0, write=10.0, pool=5.0)
            client = httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                headers={"User-Agent": "AnsiQ/1.0"},
            )
            response = await client.get(self.url)
            response.raise_for_status()
            text = response.text

            # Basic HTML to text extraction
            text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text
        except Exception as e:
            logger.warning("Failed to fetch URL %s: %s", self.url, e)
            return ""
        finally:
            # Always close the client to avoid unclosed-transport warnings on
            # Windows + Python 3.14 when an error occurs mid-handshake.
            if client is not None:
                try:
                    await client.aclose()
                except Exception:
                    pass


class DirectorySource(KnowledgeSource):
    """A knowledge source from all files in a directory."""

    def __init__(
        self,
        name: str,
        directory_path: str | Path,
        pattern: str = "*",
        metadata: dict[str, Any] | None = None,
    ):
        super().__init__(name, metadata)
        self.directory_path = Path(directory_path)
        self.pattern = pattern

    async def load(self) -> str:
        if not self.directory_path.exists() or not self.directory_path.is_dir():
            logger.warning("Knowledge directory not found: %s", self.directory_path)
            return ""

        parts: list[str] = []
        for file_path in sorted(self.directory_path.glob(self.pattern)):
            if file_path.suffix.lower() in FileSource.SUPPORTED_EXTENSIONS:
                source = FileSource(file_path.name, file_path)
                content = await source.load()
                if content:
                    parts.append(f"--- {file_path.name} ---\n{content}")

        return "\n\n".join(parts)

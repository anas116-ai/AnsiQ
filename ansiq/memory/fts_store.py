"""FTS5-based full-text search memory store.

Stores agent memories in a local SQLite FTS5 database
for fast, full-text searchable recall across sessions.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path.home() / ".ansiq" / "memory.db"


class FTSMemoryStore:
    """Persistent memory store using SQLite FTS5 full-text search.

    Thread-safe. Stores memories with metadata, tags, and timestamps.
    """

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path or _DEFAULT_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        """Initialize the database schema."""
        conn = self._get_conn()
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories USING fts5(
                content,
                summary,
                tags,
                agent_id,
                session_id,
                timestamp,
                metadata,
                content_hash UNINDEXED
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag TEXT NOT NULL,
                memory_rowid INTEGER NOT NULL,
                FOREIGN KEY (memory_rowid) REFERENCES memories(rowid)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_tags_tag
            ON memory_tags(tag)
        """)
        conn.commit()

    def store(
        self,
        content: str,
        agent_id: str = "default",
        session_id: str = "default",
        tags: list[str] | None = None,
        summary: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Store a memory entry. Returns the rowid."""
        conn = self._get_conn()
        timestamp = datetime.now(UTC).isoformat()
        tags_str = ",".join(tags or [])
        metadata_str = json.dumps(metadata or {})
        content_hash = str(hash(content))

        cursor = conn.execute(
            """
            INSERT INTO memories (content, summary, tags, agent_id, session_id, timestamp, metadata, content_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                content,
                summary or "",
                tags_str,
                agent_id,
                session_id,
                timestamp,
                metadata_str,
                content_hash,
            ),
        )
        rowid = cursor.lastrowid

        # Insert individual tags for tag-based queries
        if tags:
            for tag in tags:
                conn.execute(
                    "INSERT INTO memory_tags (tag, memory_rowid) VALUES (?, ?)",
                    (tag.lower(), rowid),
                )

        conn.commit()
        logger.debug("Stored memory (rowid=%d) for agent '%s'", rowid, agent_id)
        return rowid

    def search(
        self,
        query: str,
        agent_id: str | None = None,
        limit: int = 10,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search memories using FTS5 full-text search."""
        conn = self._get_conn()

        conditions = ["memories MATCH ?"]
        params: list[Any] = [self._sanitize_query(query)]

        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)

        sql = f"""
            SELECT rowid, content, summary, tags, agent_id, session_id, timestamp, metadata
            FROM memories
            WHERE {" AND ".join(conditions)}
            ORDER BY rank
            LIMIT ?
        """
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()

        results = []
        for row in rows:
            result = dict(row)
            result["metadata"] = json.loads(result.get("metadata", "{}"))
            result["tags"] = result.get("tags", "").split(",") if result.get("tags") else []
            results.append(result)

        # If no FTS5 results, fall back to LIKE search
        if not results:
            results = self._like_search(query, agent_id, limit, tags)

        return results

    def _sanitize_query(self, query: str) -> str:
        """Sanitize a query string for FTS5.

        Escapes special FTS5 characters and constructs a proper query.
        Multi-word queries use AND by default for precision.
        """
        # Escape special FTS5 characters and wrap terms
        terms = query.replace('"', '""').split()
        escaped = []
        for term in terms:
            if not term.strip():
                continue
            if any(c in term for c in '*"()^~+-'):
                escaped.append(f'"{term}"')
            else:
                escaped.append(term)
        if not escaped:
            return query
        return " AND ".join(escaped) if len(escaped) > 1 else escaped[0]

    def _like_search(
        self,
        query: str,
        agent_id: str | None = None,
        limit: int = 10,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fallback LIKE-based search when FTS5 returns no results."""
        conn = self._get_conn()
        conditions: list[str] = []
        params: list[Any] = []

        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)

        if tags:
            placeholders = ",".join("?" for _ in tags)
            conditions.append(
                f"rowid IN (SELECT memory_rowid FROM memory_tags WHERE tag IN ({placeholders}))"
            )
            params.extend(t.lower() for t in tags)

        # Use LIKE on the content
        like_conditions = []
        for term in query.split():
            like_conditions.append("content LIKE ?")
            params.append(f"%{term}%")

        if like_conditions:
            conditions.append(f"({' OR '.join(like_conditions)})")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT rowid, content, summary, tags, agent_id, session_id, timestamp, metadata FROM memories {where} ORDER BY rowid DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        results = []
        for row in rows:
            result = dict(row)
            result["metadata"] = json.loads(result.get("metadata", "{}"))
            result["tags"] = result.get("tags", "").split(",") if result.get("tags") else []
            results.append(result)
        return results

    def get_by_tags(
        self,
        tags: list[str],
        agent_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Retrieve memories by tags."""
        conn = self._get_conn()
        conditions: list[str] = []
        params: list[Any] = []

        placeholders = ",".join("?" for _ in tags)
        conditions.append(
            f"rowid IN (SELECT memory_rowid FROM memory_tags WHERE tag IN ({placeholders}))"
        )
        params.extend(t.lower() for t in tags)

        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)

        sql = f"""
            SELECT rowid, content, summary, tags, agent_id, session_id, timestamp, metadata
            FROM memories
            WHERE {" AND ".join(conditions)}
            ORDER BY rowid DESC
            LIMIT ?
        """
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        results = []
        for row in rows:
            result = dict(row)
            result["metadata"] = json.loads(result.get("metadata", "{}"))
            results.append(result)
        return results

    def get_recent(
        self,
        agent_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get the most recent memories."""
        conn = self._get_conn()
        if agent_id:
            rows = conn.execute(
                "SELECT rowid, content, summary, tags, agent_id, session_id, timestamp, metadata FROM memories WHERE agent_id = ? ORDER BY rowid DESC LIMIT ?",
                (agent_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT rowid, content, summary, tags, agent_id, session_id, timestamp, metadata FROM memories ORDER BY rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()

        results = []
        for row in rows:
            result = dict(row)
            result["metadata"] = json.loads(result.get("metadata", "{}"))
            results.append(result)
        return results

    def get_relevant_context(
        self,
        query: str = "",
        agent_id: str = "default",
        limit: int = 5,
    ) -> str:
        """Get relevant memories formatted as context string."""
        if query:
            memories = self.search(query, agent_id=agent_id, limit=limit)
        else:
            memories = self.get_recent(agent_id=agent_id, limit=limit)

        if not memories:
            return ""

        parts = ["## Relevant Past Experiences\n"]
        for mem in memories:
            timestamp = mem.get("timestamp", "unknown")
            summary = mem.get("summary", "")
            content = mem.get("content", "")
            if summary:
                parts.append(f"- [{timestamp}] {summary}")
            else:
                parts.append(f"- [{timestamp}] {content[:200]}...")
        return "\n".join(parts)

    def count(self, agent_id: str | None = None) -> int:
        """Count stored memories."""
        conn = self._get_conn()
        if agent_id:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM memories WHERE agent_id = ?", (agent_id,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) as cnt FROM memories").fetchone()
        return row["cnt"] if row else 0

    def delete_old(self, days: int = 30) -> int:
        """Delete memories older than the specified number of days."""
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM memories WHERE timestamp < ?",
            (datetime.now(UTC).isoformat(),),
        )
        deleted = cursor.rowcount
        conn.commit()
        logger.info("Deleted %d old memories", deleted)
        return deleted

    def close(self) -> None:
        """Close the database connection."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

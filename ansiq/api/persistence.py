"""SQLite persistence for API agents and crews — survives server restarts."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Default DB path — inside the user's data directory or project root
_DEFAULT_DB_DIR = Path(
    os.environ.get(
        "ANSIQ_DATA_DIR",
        Path.home() / ".ansiq",
    )
)
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "api_state.db"


class ApiPersistence:
    """SQLite-backed persistence for agents and crews created via the API.

    Stores serializable configuration data, not full object instances.
    Agents and crews are reconstructed from config on server start.
    """

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(_DEFAULT_DB_PATH)
        self._local = threading.local()
        self._init_db()

    @property
    def _conn(self) -> sqlite3.Connection:
        """Get a thread-local connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        # Ensure directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS agents (
                id          TEXT PRIMARY KEY,
                role        TEXT NOT NULL,
                goal        TEXT NOT NULL,
                backstory   TEXT DEFAULT '',
                llm_provider TEXT DEFAULT 'openai',
                llm_model   TEXT DEFAULT 'gpt-4o',
                temperature REAL DEFAULT 0.7,
                created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            );

            CREATE TABLE IF NOT EXISTS crews (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                process     TEXT DEFAULT 'pipeline',
                agents_json TEXT DEFAULT '[]',
                tasks_json  TEXT DEFAULT '[]',
                created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            );
        """)
        self._conn.commit()

    # ── Agents ──

    def save_agent(
        self,
        agent_id: str,
        role: str,
        goal: str,
        backstory: str = "",
        llm_provider: str = "openai",
        llm_model: str = "gpt-4o",
        temperature: float = 0.7,
    ) -> None:
        """Insert or replace an agent record."""
        self._conn.execute(
            """INSERT OR REPLACE INTO agents
               (id, role, goal, backstory, llm_provider, llm_model, temperature, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?,
                       COALESCE((SELECT created_at FROM agents WHERE id = ?),
                                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))""",
            (agent_id, role, goal, backstory, llm_provider, llm_model, temperature, agent_id),
        )
        self._conn.commit()

    def delete_agent(self, agent_id: str) -> bool:
        """Delete an agent by ID. Returns True if deleted."""
        cursor = self._conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    def load_agents(self) -> list[dict[str, Any]]:
        """Load all agents as dicts."""
        cursor = self._conn.execute(
            "SELECT id, role, goal, backstory, llm_provider, llm_model, temperature, created_at "
            "FROM agents ORDER BY created_at DESC"
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Get a single agent by ID."""
        cursor = self._conn.execute(
            "SELECT id, role, goal, backstory, llm_provider, llm_model, temperature, created_at "
            "FROM agents WHERE id = ?",
            (agent_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    # ── Crews ──

    def save_crew(
        self,
        crew_id: str,
        name: str,
        process: str = "pipeline",
        agents: list[dict[str, Any]] | None = None,
        tasks: list[dict[str, Any]] | None = None,
    ) -> None:
        """Insert or replace a crew record."""
        self._conn.execute(
            """INSERT OR REPLACE INTO crews
               (id, name, process, agents_json, tasks_json, created_at)
               VALUES (?, ?, ?, ?, ?,
                       COALESCE((SELECT created_at FROM crews WHERE id = ?),
                                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))""",
            (
                crew_id,
                name,
                process,
                json.dumps(agents or []),
                json.dumps(tasks or []),
                crew_id,
            ),
        )
        self._conn.commit()

    def delete_crew(self, crew_id: str) -> bool:
        """Delete a crew by ID. Returns True if deleted."""
        cursor = self._conn.execute("DELETE FROM crews WHERE id = ?", (crew_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    def load_crews(self) -> list[dict[str, Any]]:
        """Load all crews as dicts."""
        cursor = self._conn.execute(
            "SELECT id, name, process, agents_json, tasks_json, created_at "
            "FROM crews ORDER BY created_at DESC"
        )
        results = []
        for row in cursor.fetchall():
            d = dict(row)
            d["agents"] = json.loads(d.pop("agents_json", "[]"))
            d["tasks"] = json.loads(d.pop("tasks_json", "[]"))
            results.append(d)
        return results

    def get_crew(self, crew_id: str) -> dict[str, Any] | None:
        """Get a single crew by ID."""
        cursor = self._conn.execute(
            "SELECT id, name, process, agents_json, tasks_json, created_at FROM crews WHERE id = ?",
            (crew_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        d["agents"] = json.loads(d.pop("agents_json", "[]"))
        d["tasks"] = json.loads(d.pop("tasks_json", "[]"))
        return d

    def close(self) -> None:
        """Close the connection if open."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

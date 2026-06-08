"""Episodic memory — summarizes and retrieves past experiences.

Maintains a timeline of agent experiences with LLM-summarized
compressions for efficient long-term recall.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from ansiq.memory.fts_store import FTSMemoryStore

logger = logging.getLogger(__name__)


class EpisodicMemory:
    """Episodic memory — stores experiences as episodes with summaries.

    Each episode captures a task execution or interaction,
    summarized for efficient recall.
    """

    def __init__(
        self,
        store: FTSMemoryStore | None = None,
        agent_id: str = "default",
    ):
        self.store = store or FTSMemoryStore()
        self.agent_id = agent_id
        self._current_episode: dict[str, Any] | None = None

    def begin_episode(
        self,
        goal: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Start a new episode (e.g., a task execution session).

        Returns the episode ID.
        """
        episode_id = f"ep_{datetime.now(UTC).timestamp():.0f}_{hash(goal) % 10000}"
        self._current_episode = {
            "id": episode_id,
            "goal": goal,
            "start_time": datetime.now(UTC).isoformat(),
            "steps": [],
            "metadata": metadata or {},
        }
        logger.debug("Started episode: %s — %s", episode_id, goal[:80])
        return episode_id

    def record_step(
        self,
        action: str,
        result: str,
        success: bool = True,
    ) -> None:
        """Record a step within the current episode."""
        if self._current_episode is None:
            logger.warning("No active episode to record step")
            return

        self._current_episode["steps"].append(
            {
                "action": action,
                "result": result[:500],
                "success": success,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    def end_episode(
        self,
        summary: str | None = None,
        outcome: str = "completed",
    ) -> str | None:
        """End the current episode and persist it to memory.

        Returns the episode ID if successful.
        """
        if self._current_episode is None:
            logger.warning("No active episode to end")
            return None

        episode = self._current_episode
        episode["end_time"] = datetime.now(UTC).isoformat()
        episode["outcome"] = outcome

        if summary:
            episode["summary"] = summary
        else:
            steps_count = len(episode["steps"])
            episode["summary"] = (
                f"Episode: {episode['goal'][:100]} ({steps_count} steps, {outcome})"
            )

        # Store in FTS memory
        content_parts = [
            f"Goal: {episode['goal']}",
            f"Outcome: {outcome}",
        ]
        for step in episode["steps"]:
            content_parts.append(
                f"- Action: {step['action']} → {'✓' if step['success'] else '✗'} {step['result'][:200]}"
            )

        self.store.store(
            content="\n".join(content_parts),
            agent_id=self.agent_id,
            tags=["episode", outcome],
            summary=episode["summary"],
            metadata={
                "episode_id": episode["id"],
                "goal": episode["goal"],
                "steps": len(episode["steps"]),
                "duration": episode.get("end_time", ""),
                "outcome": outcome,
            },
        )

        episode_id = episode["id"]
        self._current_episode = None
        logger.debug("Ended episode: %s — %s", episode_id, outcome)
        return episode_id

    def recall(
        self,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Recall past episodes similar to the query."""
        memories = self.store.search(query, agent_id=self.agent_id, limit=limit)
        return [
            {
                "episode_id": m.get("metadata", {}).get("episode_id", ""),
                "summary": m.get("summary", ""),
                "content": m.get("content", ""),
                "timestamp": m.get("timestamp", ""),
                "tags": m.get("tags", []),
            }
            for m in memories
            if "episode" in m.get("tags", [])
        ]

    def get_recent_episodes(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get the most recent episodes."""
        memories = self.store.get_recent(agent_id=self.agent_id, limit=limit)
        return [
            {
                "episode_id": m.get("metadata", {}).get("episode_id", ""),
                "summary": m.get("summary", ""),
                "timestamp": m.get("timestamp", ""),
            }
            for m in memories
            if "episode" in m.get("tags", [])
        ]

    def get_relevant_context(self, query: str = "", limit: int = 5) -> str:
        """Get formatted context string from past episodes."""
        return self.store.get_relevant_context(query, self.agent_id, limit)

"""Plugin Base Classes — contract every AnsiQ plugin must fulfill.

Usage:
    class MyPlugin(AnsiqPlugin):
        @property
        def info(self) -> PluginInfo:
            return PluginInfo(
                name="my-plugin",
                version="1.0.0",
                description="My awesome plugin",
                author="Developer",
                capabilities=[PluginCapability.TOOL],
            )

        async def activate(self) -> None:
            # Plugin activation logic
            pass

        async def deactivate(self) -> None:
            # Plugin deactivation logic
            pass
"""

from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PluginCapability(StrEnum):
    """Types of capabilities a plugin can provide."""

    TOOL = "tool"
    """Adds new tools to agents."""

    LLM_PROVIDER = "llm_provider"
    """Adds a new LLM provider."""

    MEMORY_BACKEND = "memory_backend"
    """Adds a memory storage backend."""

    KNOWLEDGE_SOURCE = "knowledge_source"
    """Adds a knowledge source for RAG."""

    UI_COMPONENT = "ui_component"
    """Adds UI components to the dashboard."""

    HOOK = "hook"
    """Registers lifecycle hooks."""

    SSO_PROVIDER = "sso_provider"
    """Adds an SSO authentication provider."""

    SANDBOX_BACKEND = "sandbox_backend"
    """Adds a sandbox execution backend."""

    CLI_COMMAND = "cli_command"
    """Adds CLI commands."""

    SCHEDULED_TASK = "scheduled_task"
    """Registers background/scheduled tasks."""


class PluginInfo(BaseModel):
    """Metadata about a plugin — immutable once created."""

    name: str
    """Unique plugin name (e.g., 'ansiq-openai-tools')."""

    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    license: str = "MIT"

    # AnsiQ version compatibility
    min_ansiq_version: str = "0.2.0"
    max_ansiq_version: str = "1.0.0"

    # What this plugin provides
    capabilities: list[PluginCapability] = Field(default_factory=list)

    # Dependencies on other plugins
    dependencies: list[str] = Field(default_factory=list)
    """List of required plugin names (e.g., ['ansiq-core-tools'])."""

    # Optional metadata
    homepage: str = ""
    repository: str = ""
    keywords: list[str] = Field(default_factory=list)

    # Internal
    id: str = Field(default_factory=lambda: f"plugin_{uuid.uuid4().hex[:8]}")
    installed_at: float | None = None
    last_loaded_at: float | None = None
    load_count: int = 0
    active: bool = True
    error: str | None = None


class AnsiqPlugin(ABC):
    """Base class for all AnsiQ plugins.

    Every plugin must:
    1. Implement the `info` property
    2. Implement `activate()` — called when plugin is loaded
    3. Implement `deactivate()` — called when plugin is unloaded

    Optional overrides:
    - `on_agent_created` — react to new agent creation
    - `on_crew_executed` — react to crew execution
    - `register_tools` — register tools with agents
    - `get_config_schema` — expose configurable options
    """

    @property
    @abstractmethod
    def info(self) -> PluginInfo:
        """Return plugin metadata."""
        ...

    @abstractmethod
    async def activate(self) -> None:
        """Called when the plugin is loaded. Register tools, hooks, etc."""
        ...

    @abstractmethod
    async def deactivate(self) -> None:
        """Called when the plugin is unloaded. Cleanup resources."""
        ...

    async def on_agent_created(self, agent: Any) -> None:
        """Optional hook: called after a new agent is created."""
        pass

    async def on_crew_executed(self, crew: Any, result: Any) -> None:
        """Optional hook: called after crew execution completes."""
        pass

    async def on_task_completed(self, task: Any, result: Any) -> None:
        """Optional hook: called after a task is completed."""
        pass

    async def register_tools(self, agent: Any) -> list[Any]:
        """Return a list of tool instances to add to an agent."""
        return []

    async def register_llm_providers(self) -> list[Any]:
        """Return a list of (name, provider_class) tuples."""
        return []

    def get_config_schema(self) -> dict[str, Any]:
        """Return a JSON Schema dict describing configurable options."""
        return {}

    def __repr__(self) -> str:
        return f"Plugin({self.info.name}@{self.info.version})"

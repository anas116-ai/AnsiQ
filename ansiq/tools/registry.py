"""Tool Registry — central registry for all tools.

Tools can be registered globally and discovered by name or category.
"""

from __future__ import annotations

import logging
from typing import Any

from ansiq.tools.base import BaseTool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Global registry for tools that agents can discover and use."""

    _tools: dict[str, BaseTool] = {}

    @classmethod
    def register(cls, tool: BaseTool) -> None:
        """Register a tool globally."""
        cls._tools[tool.name] = tool
        logger.debug("Registered tool: %s", tool.name)

    @classmethod
    def register_class(cls, tool_cls: type[BaseTool]) -> None:
        """Register a tool class (instantiates it)."""
        instance = tool_cls()
        cls.register(instance)

    @classmethod
    def get(cls, name: str) -> BaseTool | None:
        """Get a tool by name."""
        return cls._tools.get(name)

    @classmethod
    def unregister(cls, name: str) -> None:
        """Remove a tool from the registry."""
        cls._tools.pop(name, None)

    @classmethod
    def list_tools(cls) -> list[BaseTool]:
        """Get all registered tools."""
        return list(cls._tools.values())

    @classmethod
    def list_by_category(cls, category: str) -> list[BaseTool]:
        """Get tools by their type/category."""
        category = category.lower()
        return [t for t in cls._tools.values() if t.__class__.__module__.lower().endswith(category)]

    @classmethod
    def get_schemas(cls) -> list[dict[str, Any]]:
        """Get OpenAI-compatible function schemas for all tools."""
        return [tool.to_function_schema() for tool in cls._tools.values()]

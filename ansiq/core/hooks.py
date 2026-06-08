"""Agent Hooks — pre/post execution lifecycle hooks.

Inspired by Hermes Agent's agent-hooks system.
Allows running custom logic before/after tasks, on errors,
and during the agent lifecycle.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class HookEvent(StrEnum):
    """Lifecycle events where hooks can be attached."""

    BEFORE_TASK = "before_task"
    """Before an agent starts a task."""

    AFTER_TASK = "after_task"
    """After an agent completes a task."""

    ON_ERROR = "on_error"
    """When an agent encounters an error."""

    BEFORE_TOOL = "before_tool"
    """Before a tool is executed."""

    AFTER_TOOL = "after_tool"
    """After a tool is executed."""

    ON_STREAM = "on_stream"
    """During streaming output."""

    ON_STARTUP = "on_startup"
    """When the agent is initialized."""

    ON_SHUTDOWN = "on_shutdown"
    """When the agent is shutting down."""


class HookResult:
    """Result of a hook execution."""

    def __init__(
        self,
        success: bool = True,
        abort: bool = False,
        modify_input: dict[str, Any] | None = None,
        modify_output: str | None = None,
        error: str | None = None,
    ):
        self.success = success
        self.abort = abort
        self.modify_input = modify_input
        self.modify_output = modify_output
        self.error = error


class Hook:
    """A single hook with metadata."""

    def __init__(
        self,
        name: str,
        handler: Callable,
        event: HookEvent,
        priority: int = 0,
        once: bool = False,
    ):
        self.name = name
        self.handler = handler
        self.event = event
        self.priority = priority
        self.once = once
        self.executed = False

    async def execute(self, **kwargs: Any) -> HookResult:
        """Execute the hook handler."""
        try:
            if callable(self.handler):
                result = self.handler(**kwargs)
                if hasattr(result, "__await__"):
                    result = await result
                if isinstance(result, HookResult):
                    return result
                return HookResult(success=True)
            return HookResult(success=True)
        except Exception as e:
            logger.error("Hook '%s' failed: %s", self.name, e)
            return HookResult(success=False, error=str(e))


class HookRegistry:
    """Global registry for hooks.

    Hooks can be registered globally (affect all agents) or
    per-agent (affect only that agent instance).
    """

    _global_hooks: dict[HookEvent, list[Hook]] = {}

    @classmethod
    def register(
        cls,
        event: HookEvent,
        handler: Callable,
        name: str | None = None,
        priority: int = 0,
        once: bool = False,
    ) -> Hook:
        """Register a global hook."""
        hook = Hook(
            name=name or f"hook_{handler.__name__}_{event.value}",
            handler=handler,
            event=event,
            priority=priority,
            once=once,
        )
        if event not in cls._global_hooks:
            cls._global_hooks[event] = []
        cls._global_hooks[event].append(hook)
        cls._global_hooks[event].sort(key=lambda h: h.priority, reverse=True)
        logger.debug("Registered global hook: %s on %s", hook.name, event.value)
        return hook

    @classmethod
    def get_hooks(cls, event: HookEvent) -> list[Hook]:
        """Get all hooks for an event."""
        hooks = list(cls._global_hooks.get(event, []))
        return hooks

    @classmethod
    def unregister(cls, name: str) -> bool:
        """Unregister a hook by name."""
        for event in list(cls._global_hooks.keys()):
            for i, hook in enumerate(cls._global_hooks[event]):
                if hook.name == name:
                    cls._global_hooks[event].pop(i)
                    if not cls._global_hooks[event]:
                        del cls._global_hooks[event]
                    return True
        return False

    @classmethod
    def clear(cls) -> None:
        """Clear all global hooks."""
        cls._global_hooks.clear()


class AgentHooks:
    """Manages hooks for a specific agent instance.

    Combines global hooks with agent-specific hooks.
    """

    def __init__(self):
        self._agent_hooks: dict[HookEvent, list[Hook]] = {}

    def register(
        self,
        event: HookEvent,
        handler: Callable,
        name: str | None = None,
        priority: int = 0,
        once: bool = False,
    ) -> Hook:
        """Register an agent-specific hook."""
        hook = Hook(
            name=name or f"agent_hook_{handler.__name__}_{event.value}",
            handler=handler,
            event=event,
            priority=priority,
            once=once,
        )
        if event not in self._agent_hooks:
            self._agent_hooks[event] = []
        self._agent_hooks[event].append(hook)
        self._agent_hooks[event].sort(key=lambda h: h.priority, reverse=True)
        return hook

    async def execute(
        self,
        event: HookEvent,
        **kwargs: Any,
    ) -> list[HookResult]:
        """Execute all hooks for an event.

        Returns a list of HookResults. If any hook sets abort=True,
        subsequent hooks are skipped.
        """
        results: list[HookResult] = []
        hooks = []

        # Combine global and agent hooks
        hooks.extend(HookRegistry.get_hooks(event))
        hooks.extend(self._agent_hooks.get(event, []))
        hooks.sort(key=lambda h: h.priority, reverse=True)

        for hook in hooks:
            if hook.once and hook.executed:
                continue

            result = await hook.execute(**kwargs)
            results.append(result)
            hook.executed = True

            if result.abort:
                logger.info("Hook '%s' requested abort", hook.name)
                break

            # Apply input modifications
            if result.modify_input:
                for key, value in result.modify_input.items():
                    if key in kwargs:
                        kwargs[key] = value

            # Apply output modifications
            if result.modify_output is not None:
                kwargs["_output"] = result.modify_output

        return results

    def get_hooks(self, event: HookEvent) -> list[Hook]:
        """Get all hooks for an event (global + agent)."""
        hooks = list(HookRegistry.get_hooks(event))
        hooks.extend(self._agent_hooks.get(event, []))
        hooks.sort(key=lambda h: h.priority, reverse=True)
        return hooks

    def clear(self) -> None:
        """Clear agent-specific hooks."""
        self._agent_hooks.clear()

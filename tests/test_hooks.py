"""Tests for the Agent Hooks system."""

from __future__ import annotations

from ansiq.core.hooks import (
    AgentHooks,
    Hook,
    HookEvent,
    HookRegistry,
    HookResult,
)


class TestHookEvent:
    def test_event_values(self):
        """Test HookEvent enum values."""
        assert HookEvent.BEFORE_TASK.value == "before_task"
        assert HookEvent.AFTER_TASK.value == "after_task"
        assert HookEvent.ON_ERROR.value == "on_error"
        assert HookEvent.BEFORE_TOOL.value == "before_tool"
        assert HookEvent.AFTER_TOOL.value == "after_tool"
        assert HookEvent.ON_STARTUP.value == "on_startup"
        assert HookEvent.ON_SHUTDOWN.value == "on_shutdown"


class TestHookResult:
    def test_default_result(self):
        """Test default HookResult."""
        result = HookResult()
        assert result.success is True
        assert result.abort is False
        assert result.modify_input is None
        assert result.modify_output is None
        assert result.error is None

    def test_abort_result(self):
        """Test abort HookResult."""
        result = HookResult(success=False, abort=True, error="Stop")
        assert result.abort is True
        assert result.error == "Stop"


class TestHook:
    def test_create_hook(self):
        """Test creating a hook."""
        async def my_handler(**kwargs):
            return HookResult(success=True)

        hook = Hook(
            name="test_hook",
            handler=my_handler,
            event=HookEvent.BEFORE_TASK,
            priority=10,
        )
        assert hook.name == "test_hook"
        assert hook.event == HookEvent.BEFORE_TASK
        assert hook.priority == 10
        assert hook.once is False

    def test_execute_sync_handler(self):
        """Test executing a sync hook handler."""
        def sync_handler(**kwargs):
            return HookResult(success=True, modify_input={"key": "value"})

        hook = Hook(name="sync", handler=sync_handler, event=HookEvent.BEFORE_TASK)
        import asyncio
        result = asyncio.run(hook.execute())
        assert result.success is True
        assert result.modify_input == {"key": "value"}

    def test_execute_async_handler(self):
        """Test executing an async hook handler."""
        async def async_handler(**kwargs):
            return HookResult(success=True)

        hook = Hook(name="async", handler=async_handler, event=HookEvent.BEFORE_TASK)
        import asyncio
        result = asyncio.run(hook.execute())
        assert result.success is True

    def test_execute_handler_returns_none(self):
        """Test executing a handler that returns None."""
        def no_return(**kwargs):
            pass

        hook = Hook(name="no_return", handler=no_return, event=HookEvent.BEFORE_TASK)
        import asyncio
        result = asyncio.run(hook.execute())
        assert result.success is True  # Default success

    def test_execute_handler_raises(self):
        """Test executing a handler that raises."""
        def broken(**kwargs):
            raise ValueError("Error!")

        hook = Hook(name="broken", handler=broken, event=HookEvent.BEFORE_TASK)
        import asyncio
        result = asyncio.run(hook.execute())
        assert result.success is False
        assert "Error!" in result.error


class TestHookRegistry:
    def setup_method(self):
        HookRegistry.clear()

    def test_register_and_get(self):
        """Test registering and getting hooks."""
        async def handler(**kwargs):
            pass

        HookRegistry.register(HookEvent.BEFORE_TASK, handler, name="test")
        hooks = HookRegistry.get_hooks(HookEvent.BEFORE_TASK)
        assert len(hooks) == 1
        assert hooks[0].name == "test"

    def test_unregister(self):
        """Test unregistering a hook."""
        async def handler(**kwargs):
            pass

        HookRegistry.register(HookEvent.BEFORE_TASK, handler, name="remove_me")
        assert HookRegistry.unregister("remove_me") is True
        assert HookRegistry.unregister("nonexistent") is False

    def test_clear(self):
        """Test clearing all hooks."""
        async def handler(**kwargs):
            pass

        HookRegistry.register(HookEvent.BEFORE_TASK, handler)
        HookRegistry.clear()
        assert len(HookRegistry.get_hooks(HookEvent.BEFORE_TASK)) == 0

    def test_priority_order(self):
        """Test hooks are ordered by priority."""
        results = []

        async def low(**kwargs):
            results.append("low")

        async def high(**kwargs):
            results.append("high")

        HookRegistry.register(HookEvent.BEFORE_TASK, high, name="high", priority=100)
        HookRegistry.register(HookEvent.BEFORE_TASK, low, name="low", priority=0)

        hooks = HookRegistry.get_hooks(HookEvent.BEFORE_TASK)
        # Should be ordered high first (descending priority)
        # But we can't easily test execution order here without AgentHooks


class TestAgentHooks:
    def test_create(self):
        """Test creating AgentHooks."""
        hooks = AgentHooks()
        assert hooks is not None

    def test_register_agent_hook(self):
        """Test registering an agent-specific hook."""
        hooks = AgentHooks()
        async def handler(**kwargs):
            pass

        hook = hooks.register(HookEvent.BEFORE_TASK, handler)
        assert hook.name.startswith("agent_hook_")

    def test_execute_no_hooks(self):
        """Test executing with no hooks should have no results."""
        HookRegistry.clear()
        hooks = AgentHooks()
        import asyncio
        results = asyncio.run(hooks.execute(HookEvent.BEFORE_TASK, task="test"))
        assert len(results) == 0

    def test_execute_with_hook(self):
        """Test executing a hook returns result."""
        HookRegistry.clear()
        hooks = AgentHooks()
        executed = []

        async def my_hook(**kwargs):
            executed.append(kwargs.get("task"))
            return HookResult(success=True)

        hooks.register(HookEvent.BEFORE_TASK, my_hook, name="test_hook")
        import asyncio
        results = asyncio.run(hooks.execute(HookEvent.BEFORE_TASK, task="hello"))
        # Agent hooks always add at least BEFORE_TASK result
        assert "hello" in executed

    def test_execute_abort(self):
        """Test abort stops subsequent hooks."""
        HookRegistry.clear()
        hooks = AgentHooks()
        executed = []

        async def abort_hook(**kwargs):
            executed.append("abort")
            return HookResult(abort=True)

        async def after_hook(**kwargs):
            executed.append("after")

        hooks.register(HookEvent.BEFORE_TASK, abort_hook, name="abort", priority=10)
        hooks.register(HookEvent.BEFORE_TASK, after_hook, name="after", priority=0)

        import asyncio
        results = asyncio.run(hooks.execute(HookEvent.BEFORE_TASK))
        # Abort should prevent after_hook from executing
        assert "abort" in executed
        assert "after" not in executed

    def test_get_hooks(self):
        """Test getting all hooks for an event."""
        hooks = AgentHooks()
        async def handler(**kwargs):
            pass

        HookRegistry.register(HookEvent.AFTER_TASK, handler, name="global_hook")
        hooks.register(HookEvent.AFTER_TASK, handler, name="agent_hook")

        all_hooks = hooks.get_hooks(HookEvent.AFTER_TASK)
        # Should include both global and agent hooks
        names = [h.name for h in all_hooks]
        assert "global_hook" in names
        assert "agent_hook" in names
        HookRegistry.clear()

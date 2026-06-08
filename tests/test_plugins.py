"""Tests for the plugins module — AnsiqPlugin, PluginInfo, PluginManager."""

from __future__ import annotations

import asyncio

import pytest

from ansiq.plugins.base import (
    AnsiqPlugin,
    PluginCapability,
    PluginInfo,
)


class TestPluginCapability:
    """Test PluginCapability enum."""

    def test_capability_values(self):
        assert PluginCapability.TOOL.value == "tool"
        assert PluginCapability.LLM_PROVIDER.value == "llm_provider"
        assert PluginCapability.MEMORY_BACKEND.value == "memory_backend"
        assert PluginCapability.CLI_COMMAND.value == "cli_command"

    def test_all_capabilities_count(self):
        assert len(list(PluginCapability)) == 10


class TestPluginInfo:
    """Test PluginInfo model."""

    def test_minimal_plugin_info(self):
        info = PluginInfo(name="test-plugin")
        assert info.name == "test-plugin"
        assert info.version == "0.1.0"
        assert info.capabilities == []
        assert info.active is True
        assert info.id.startswith("plugin_")

    def test_full_plugin_info(self):
        info = PluginInfo(
            name="my-plugin", version="1.2.3", description="My plugin",
            author="Developer", license="Apache 2.0",
            capabilities=[PluginCapability.TOOL, PluginCapability.HOOK],
            dependencies=["ansiq-core-tools"],
        )
        assert info.name == "my-plugin"
        assert len(info.capabilities) == 2


class TestAnsiqPlugin:
    """Test AnsiqPlugin base class."""

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            AnsiqPlugin()

    def test_concrete_plugin(self):
        class TestPlugin(AnsiqPlugin):
            @property
            def info(self) -> PluginInfo:
                return PluginInfo(name="test-plugin", version="1.0.0",
                                  description="A test plugin",
                                  capabilities=[PluginCapability.TOOL])

            async def activate(self) -> None:
                pass

            async def deactivate(self) -> None:
                pass

        plugin = TestPlugin()
        assert plugin.info.name == "test-plugin"
        assert plugin.info.version == "1.0.0"

    def test_plugin_repr(self):
        class TestPlugin(AnsiqPlugin):
            @property
            def info(self) -> PluginInfo:
                return PluginInfo(name="repr-plugin", version="2.0.0")

            async def activate(self) -> None:
                pass

            async def deactivate(self) -> None:
                pass

        plugin = TestPlugin()
        assert "repr-plugin" in repr(plugin)

    @pytest.mark.asyncio
    async def test_default_hooks_return_empty(self):
        class TestPlugin(AnsiqPlugin):
            @property
            def info(self) -> PluginInfo:
                return PluginInfo(name="hook-test")

            async def activate(self) -> None:
                pass

            async def deactivate(self) -> None:
                pass

        plugin = TestPlugin()

        # Must await async methods
        tools = await plugin.register_tools(None)
        assert tools == []

        providers = await plugin.register_llm_providers()
        assert providers == []

        assert plugin.get_config_schema() == {}

        # Optional hooks should not raise
        await plugin.on_agent_created(None)
        await plugin.on_crew_executed(None, None)
        await plugin.on_task_completed(None, None)


class TestPluginManager:
    """Test PluginManager initialization and operations."""

    def test_create_manager(self, tmp_path):
        from ansiq.plugins.manager import PluginManager
        mgr = PluginManager(config_path=tmp_path)
        assert mgr.list_plugins() == []

    def test_list_plugins_empty(self, tmp_path):
        from ansiq.plugins.manager import PluginManager
        mgr = PluginManager(config_path=tmp_path)
        assert mgr.list_plugins() == []

    def test_get_plugin_nonexistent(self, tmp_path):
        from ansiq.plugins.manager import PluginManager
        mgr = PluginManager(config_path=tmp_path)
        assert mgr.get_plugin("nonexistent") is None

    def test_has_plugin(self, tmp_path):
        from ansiq.plugins.manager import PluginManager
        mgr = PluginManager(config_path=tmp_path)
        assert mgr.has_plugin("anything") is False

    def test_disable_enable_plugin(self, tmp_path):
        from ansiq.plugins.manager import PluginManager
        mgr = PluginManager(config_path=tmp_path)
        mgr.disable("bad-plugin")
        assert "bad-plugin" in mgr.disabled_plugins
        mgr.enable("bad-plugin")
        assert "bad-plugin" not in mgr.disabled_plugins

    def test_load_nonexistent_raises(self, tmp_path):
        from ansiq.plugins.manager import PluginManager
        mgr = PluginManager(config_path=tmp_path)
        with pytest.raises(ValueError, match="not found"):
            asyncio.run(mgr.load("nonexistent-plugin"))

    def test_get_stats_empty(self, tmp_path):
        from ansiq.plugins.manager import PluginManager
        mgr = PluginManager(config_path=tmp_path)
        stats = mgr.get_stats()
        assert stats["total_discovered"] == 0
        assert stats["loaded"] == 0

    def test_discover_no_entry_points(self, tmp_path):
        from ansiq.plugins.manager import PluginManager
        mgr = PluginManager(config_path=tmp_path)
        assert isinstance(mgr.discover(), list)

    def test_repr(self, tmp_path):
        from ansiq.plugins.manager import PluginManager
        mgr = PluginManager(config_path=tmp_path)
        assert "PluginManager" in repr(mgr)

    def test_persistence(self, tmp_path):
        """Test plugin registry persists across instances."""
        from ansiq.plugins.manager import PluginManager
        mgr1 = PluginManager(config_path=tmp_path)
        info1 = PluginInfo(name="persisted-plugin")
        mgr1._plugin_info["persisted-plugin"] = info1
        mgr1._save_registry()

        mgr2 = PluginManager(config_path=tmp_path)
        assert mgr2.get_plugin_info("persisted-plugin") is not None
        assert mgr2.get_plugin_info("persisted-plugin").name == "persisted-plugin"

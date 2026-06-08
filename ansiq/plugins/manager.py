"""Plugin Manager — discover, load, activate, and manage AnsiQ plugins.

Features:
- Auto-discovery via entry_points (pip-installable)
- Manual plugin registration
- Dependency resolution with topological sort
- Lifecycle management (load, activate, deactivate, unload)
- Plugin registry persistence
"""

from __future__ import annotations

import importlib
import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ansiq.plugins.base import AnsiqPlugin, PluginCapability, PluginInfo

logger = logging.getLogger(__name__)

# Entry point group for AnsiQ plugins
ENTRY_POINT_GROUP = "ansiq.plugins"


class PluginManager:
    """Discover, load, and manage AnsiQ plugins.

    Usage:
        manager = PluginManager()

        # Discover pip-installed plugins
        found = manager.discover()

        # Load a specific plugin
        plugin = await manager.load("my-plugin")

        # List loaded plugins
        for info in manager.list_plugins():
            print(info.name, info.version)
    """

    def __init__(
        self,
        config_path: Path | str | None = None,
        disabled_plugins: list[str] | None = None,
    ):
        self.config_path = Path(config_path or Path.home() / ".ansiq" / "plugins")
        self.config_path.mkdir(parents=True, exist_ok=True)

        self.disabled_plugins = set(disabled_plugins or [])

        # Plugin storage
        self._plugins: dict[str, AnsiqPlugin] = {}
        self._plugin_info: dict[str, PluginInfo] = {}

        # Event hooks
        self._on_load_callbacks: list[Callable] = []

        self._load_registry()

    # ── Discovery ──

    def discover(self) -> list[PluginInfo]:
        """Discover all available AnsiQ plugins via pip entry points.

        Plugins declare themselves via pyproject.toml:
            [project.entry-points."ansiq.plugins"]
            my_plugin = "my_package:MyPlugin"

        Returns:
            List of discovered PluginInfo (not yet loaded).
        """
        discovered: list[PluginInfo] = []

        try:
            from importlib.metadata import entry_points

            eps = entry_points()
            if hasattr(eps, "select"):
                plugin_eps = eps.select(group=ENTRY_POINT_GROUP)
            else:
                plugin_eps = eps.get(ENTRY_POINT_GROUP, [])

            for ep in plugin_eps:
                if ep.name in self.disabled_plugins:
                    logger.debug("Skipping disabled plugin: %s", ep.name)
                    continue

                try:
                    # Try to load plugin class
                    plugin_cls = ep.load()

                    # Check if it's a subclass of AnsiqPlugin
                    if isinstance(plugin_cls, type) and issubclass(plugin_cls, AnsiqPlugin):
                        # Instantiate to get info
                        plugin_instance = plugin_cls()
                        info = plugin_instance.info
                        info.installed_at = time.time()
                        discovered.append(info)
                        logger.debug("Discovered plugin: %s v%s", info.name, info.version)
                    else:
                        logger.warning("Entry point '%s' does not point to an AnsiqPlugin", ep.name)
                except Exception as e:
                    logger.warning("Failed to load entry point '%s': %s", ep.name, e)

        except ImportError:
            logger.debug("importlib.metadata not available, skipping entry point discovery")

        # Also scan for local plugin directories
        discovered.extend(self._discover_local_plugins())

        logger.info("Discovered %d plugins", len(discovered))
        return discovered

    def _discover_local_plugins(self) -> list[PluginInfo]:
        """Scan local directories for plugins."""
        plugins: list[PluginInfo] = []
        plugins_dir = self.config_path / "local"

        if not plugins_dir.exists():
            return plugins

        for item in plugins_dir.iterdir():
            if item.is_dir():
                init_file = item / "__init__.py"
                if init_file.exists():
                    try:
                        module_name = f".plugins.local.{item.name}"
                        mod = importlib.import_module(module_name)
                        if hasattr(mod, "Plugin"):
                            plugin_cls = mod.Plugin
                            if isinstance(plugin_cls, type) and issubclass(plugin_cls, AnsiqPlugin):
                                instance = plugin_cls()
                                info = instance.info
                                plugins.append(info)
                    except Exception as e:
                        logger.debug("Skipping local plugin '%s': %s", item.name, e)

        return plugins

    # ── Loading ──

    async def load(
        self,
        plugin_name: str,
        plugin_cls: type[AnsiqPlugin] | None = None,
        **kwargs: Any,
    ) -> AnsiqPlugin:
        """Load a plugin by name or class.

        If plugin_cls is provided, register it directly.
        Otherwise, search discovered plugins.
        """
        if plugin_name in self._plugins:
            logger.debug("Plugin '%s' already loaded", plugin_name)
            return self._plugins[plugin_name]

        if plugin_cls:
            plugin = plugin_cls()
        else:
            # Try to import from entry points
            plugin = await self._import_plugin(plugin_name)

        if not plugin:
            raise ValueError(f"Plugin '{plugin_name}' not found")

        info = plugin.info

        # Check compatibility
        self._check_compatibility(info)

        # Resolve dependencies
        await self._resolve_dependencies(info.dependencies)

        # Activate
        try:
            await plugin.activate()
            info.last_loaded_at = time.time()
            info.load_count += 1
            info.active = True
            info.error = None

            self._plugins[info.name] = plugin
            self._plugin_info[info.name] = info
            self._save_registry()

            logger.info("Loaded plugin: %s v%s", info.name, info.version)
            return plugin

        except Exception as e:
            info.error = str(e)
            info.active = False
            self._save_registry()
            logger.error("Failed to activate plugin '%s': %s", info.name, e)
            raise

    async def _import_plugin(self, module_path: str) -> AnsiqPlugin | None:
        """Import a plugin from a dotted module path."""
        try:
            mod = importlib.import_module(module_path)

            # Look for a Plugin class or the module itself
            plugin_cls = getattr(mod, "Plugin", None)
            if plugin_cls and isinstance(plugin_cls, type):
                return plugin_cls()

            # Check if module has get_plugin() factory
            factory = getattr(mod, "get_plugin", None)
            if callable(factory):
                result = factory()
                if isinstance(result, AnsiqPlugin):
                    return result

            return None
        except Exception as e:
            logger.warning("Failed to import plugin from '%s': %s", module_path, e)
            return None

    async def unload(self, plugin_name: str) -> bool:
        """Unload a plugin and call its deactivate method."""
        plugin = self._plugins.pop(plugin_name, None)
        if not plugin:
            return False

        try:
            await plugin.deactivate()
        except Exception as e:
            logger.warning("Error deactivating plugin '%s': %s", plugin_name, e)

        info = self._plugin_info.get(plugin_name)
        if info:
            info.active = False

        self._save_registry()
        logger.info("Unloaded plugin: %s", plugin_name)
        return True

    async def activate(self, plugin_name: str) -> bool:
        """Re-activate a previously loaded plugin."""
        plugin = self._plugins.get(plugin_name)
        if not plugin:
            return False

        try:
            await plugin.activate()
            info = plugin.info
            info.active = True
            info.error = None
            self._save_registry()
            return True
        except Exception as e:
            plugin.info.error = str(e)
            self._save_registry()
            return False

    # ── Querying ──

    def list_plugins(self, active_only: bool = False) -> list[PluginInfo]:
        """List all loaded plugins."""
        infos = list(self._plugin_info.values())
        if active_only:
            infos = [i for i in infos if i.active]
        return sorted(infos, key=lambda i: i.name)

    def get_plugin(self, name: str) -> AnsiqPlugin | None:
        """Get a loaded plugin by name."""
        return self._plugins.get(name)

    def get_plugin_info(self, name: str) -> PluginInfo | None:
        """Get plugin info by name."""
        return self._plugin_info.get(name)

    def has_plugin(self, name: str) -> bool:
        """Check if a plugin is loaded."""
        return name in self._plugins

    def get_plugins_by_capability(self, capability: PluginCapability) -> list[AnsiqPlugin]:
        """Get all plugins that provide a specific capability."""
        return [
            plugin
            for plugin in self._plugins.values()
            if plugin.info.active and capability in plugin.info.capabilities
        ]

    # ── Dependencies ──

    async def _resolve_dependencies(
        self,
        required: list[str],
        resolved: set[str] | None = None,
    ) -> None:
        """Recursively load all required plugin dependencies."""
        if not required:
            return

        resolved = resolved or set()

        for dep_name in required:
            if dep_name in resolved or dep_name in self._plugins:
                continue

            # Check if the dependency is available
            discovered = self.discover()
            dep_info = next((d for d in discovered if d.name == dep_name), None)

            if not dep_info:
                raise ValueError(
                    f"Required plugin dependency '{dep_name}' not found. "
                    f"Install it with: pip install {dep_name}"
                )

            await self.load(dep_name)
            resolved.add(dep_name)

    def _check_compatibility(self, info: PluginInfo) -> None:
        """Check if a plugin is compatible with the current AnsiQ version."""
        # Simple version check (can be enhanced with packaging.version)
        try:
            import ansiq

            current_version = getattr(ansiq, "__version__", "0.1.0")

            if current_version < info.min_ansiq_version:
                raise ValueError(
                    f"Plugin '{info.name}' requires AnsiQ >= {info.min_ansiq_version}, "
                    f"but current version is {current_version}"
                )
            if current_version > info.max_ansiq_version:
                logger.warning(
                    "Plugin '%s' was built for AnsiQ %s, current is %s",
                    info.name,
                    info.max_ansiq_version,
                    current_version,
                )
        except ImportError:
            pass

    # ── Persistence ──

    def _save_registry(self) -> None:
        """Save plugin registry to disk."""
        try:
            data = {
                "plugins": [
                    {
                        "name": info.name,
                        "version": info.version,
                        "description": info.description,
                        "author": info.author,
                        "capabilities": [c.value for c in info.capabilities],
                        "dependencies": info.dependencies,
                        "active": info.active,
                        "error": info.error,
                        "load_count": info.load_count,
                        "installed_at": info.installed_at,
                        "last_loaded_at": info.last_loaded_at,
                    }
                    for info in self._plugin_info.values()
                ]
            }
            path = self.config_path / "registry.json"
            path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.debug("Failed to save plugin registry: %s", e)

    def _load_registry(self) -> None:
        """Load plugin registry from disk."""
        try:
            path = self.config_path / "registry.json"
            if not path.exists():
                return
            data = json.loads(path.read_text())
            for item in data.get("plugins", []):
                info = PluginInfo(
                    name=item["name"],
                    version=item.get("version", "0.1.0"),
                    description=item.get("description", ""),
                    author=item.get("author", ""),
                    capabilities=[PluginCapability(c) for c in item.get("capabilities", [])],
                    dependencies=item.get("dependencies", []),
                    active=item.get("active", True),
                    error=item.get("error"),
                    load_count=item.get("load_count", 0),
                    installed_at=item.get("installed_at"),
                    last_loaded_at=item.get("last_loaded_at"),
                )
                self._plugin_info[info.name] = info
        except Exception as e:
            logger.debug("Failed to load plugin registry: %s", e)

    # ── Management ──

    def disable(self, plugin_name: str) -> None:
        """Add a plugin to the disabled list."""
        self.disabled_plugins.add(plugin_name)

    def enable(self, plugin_name: str) -> None:
        """Remove a plugin from the disabled list."""
        self.disabled_plugins.discard(plugin_name)

    async def reload(self, plugin_name: str) -> AnsiqPlugin | None:
        """Unload and reload a plugin."""
        await self.unload(plugin_name)
        return await self.load(plugin_name)

    def get_stats(self) -> dict[str, Any]:
        """Get plugin statistics."""
        all_plugins = list(self._plugin_info.values())
        return {
            "total_discovered": len(all_plugins),
            "active": len([p for p in all_plugins if p.active]),
            "loaded": len(self._plugins),
            "disabled": len(self.disabled_plugins),
            "by_capability": {
                cap.value: len([p for p in all_plugins if p.active and cap in p.capabilities])
                for cap in PluginCapability
            },
        }

    def __repr__(self) -> str:
        return f"PluginManager(loaded={len(self._plugins)}, discovered={len(self._plugin_info)})"

"""Plugin System — load, manage, and discover third-party plugins.

Provides:
- AnsiqPlugin base class — every plugin implements this
- PluginManager — discovery, loading, dependency resolution
- Plugin registry — track installed plugins
"""

from ansiq.plugins.base import AnsiqPlugin, PluginCapability, PluginInfo
from ansiq.plugins.manager import PluginManager

__all__ = [
    "AnsiqPlugin",
    "PluginInfo",
    "PluginCapability",
    "PluginManager",
]

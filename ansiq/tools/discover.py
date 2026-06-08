"""Auto-Tool Discovery — automatically discover and register tools from Python code.

Instead of manually defining tool classes, developers can:
1. Use @ansiq_tool decorator on functions
2. Write regular async functions with docstrings and type hints
3. Let the system auto-discover tools from modules

Features:
- @ansiq_tool decorator: auto-register any async function as a tool
- Module scanning: discover all tools in a Python module
- Type hint parsing: auto-generate parameter schemas
- Docstring parsing: extract descriptions for tool and parameters
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from collections.abc import Callable
from typing import Any, get_type_hints

from ansiq.tools.base import BaseTool, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

# Registry of discovered tools
_tool_registry: dict[str, type[BaseTool]] = {}
_tool_instances: dict[str, BaseTool] = {}


def ansiq_tool(
    name: str | None = None,
    description: str | None = None,
    category: str = "general",
):
    """Decorator to register a function as an AnsiQ tool.

    Usage:
        @ansiq_tool(name="search_web", description="Search the web")
        async def search_web(query: str, max_results: int = 5) -> str:
            \"\"\"Search the web for information.\"\"\"
            return f"Results for {query}"

    The decorated function becomes available as a tool that agents can use.
    Parameters are automatically inferred from type hints and docstrings.

    Args:
        name: Optional custom name for the tool (defaults to function name)
        description: Optional description (defaults to function docstring)
        category: Tool category for organization

    Returns:
        The original function (unchanged) — can still be called normally
    """

    def decorator(func: Callable) -> Callable:
        tool_name = name or func.__name__
        tool_desc = description or inspect.getdoc(func) or func.__name__

        # Create a dynamic tool class
        class DynamicTool(BaseTool):
            def __init__(self):
                self.name = tool_name
                self.description = tool_desc
                self._func = func
                self._category = category

                # Auto-generate parameters from type hints
                self.parameters = self._infer_parameters()
                super().__init__()

            def _infer_parameters(self) -> list[ToolParameter]:
                """Infer parameters from function signature and type hints."""
                sig = inspect.signature(func)
                hints = get_type_hints(func) if hasattr(func, "__annotations__") else {}

                params = []
                for param_name, param in sig.parameters.items():
                    if param_name == "self" or param_name == "cls":
                        continue

                    # Get type from hints
                    param_type = hints.get(param_name, str)
                    type_name = self._type_to_string(param_type)

                    # Get description from docstring
                    desc = self._extract_param_doc(param_name)

                    params.append(
                        ToolParameter(
                            name=param_name,
                            type=type_name,
                            description=desc or param_name,
                            required=param.default is inspect.Parameter.empty,
                        )
                    )

                return params

            def _type_to_string(self, t: type) -> str:
                """Convert Python type to schema type string."""
                if t is str:
                    return "string"
                elif t is int:
                    return "integer"
                elif t is float:
                    return "number"
                elif t is bool:
                    return "boolean"
                elif t is list:
                    return "array"
                elif t is dict:
                    return "object"
                else:
                    return "string"

            def _extract_param_doc(self, param_name: str) -> str:
                """Extract parameter description from Google-style docstring."""
                doc = inspect.getdoc(func) or ""
                lines = doc.split("\n")
                in_params = False

                for line in lines:
                    stripped = line.strip()
                    if stripped.lower().startswith(("args:", "parameters:", "params:")):
                        in_params = True
                        continue
                    elif in_params:
                        if stripped.startswith(("returns:", "raises:", "example:", "note:")):
                            break
                        if stripped.startswith(f"{param_name}:"):
                            return stripped.split(":", 1)[1].strip()
                        elif stripped.startswith(f"{param_name} ("):
                            return stripped.split(")", 1)[1].strip() if ")" in stripped else ""

                return ""

            async def execute(self, **kwargs: Any) -> ToolResult:
                """Execute the wrapped function."""
                try:
                    if inspect.iscoroutinefunction(self._func):
                        output = await self._func(**kwargs)
                    else:
                        output = self._func(**kwargs)

                    output_str = str(output) if output is not None else ""
                    return ToolResult(success=True, output=output_str, data=output)

                except Exception as e:
                    logger.error("Tool '%s' execution failed: %s", self.name, e)
                    return ToolResult(success=False, output="", error=str(e))

        # Register the tool
        _tool_registry[tool_name] = DynamicTool
        logger.debug("Registered tool: %s (from %s)", tool_name, func.__name__)

        return func

    return decorator


def discover_tools(module_name: str) -> list[BaseTool]:
    """Discover all tools in a Python module.

    Scans the module for functions decorated with @ansiq_tool
    and returns tool instances.

    Args:
        module_name: Full module path (e.g., 'myapp.tools')

    Returns:
        List of discovered tool instances

    Usage:
        tools = discover_tools("myapp.tools")
        agent.add_tool(tools[0])
    """
    discovered: list[BaseTool] = []

    try:
        module = importlib.import_module(module_name)

        # Find all @ansiq_tool decorated functions
        for _name, obj in inspect.getmembers(module):
            if inspect.isfunction(obj) or inspect.iscoroutinefunction(obj):
                # Check if registered via decorator
                if obj.__name__ in _tool_registry:
                    tool_cls = _tool_registry[obj.__name__]
                    tool = tool_cls()
                    discovered.append(tool)

        logger.info("Discovered %d tools in module '%s'", len(discovered), module_name)

    except ImportError as e:
        logger.warning("Could not import module '%s': %s", module_name, e)
    except Exception as e:
        logger.warning("Error discovering tools in '%s': %s", module_name, e)

    return discovered


def discover_tools_from_instance(obj: Any) -> list[BaseTool]:
    """Discover tool methods on an object instance.

    Finds methods decorated with @ansiq_tool on an object.

    Args:
        obj: An object instance to scan for tools

    Returns:
        List of discovered tool instances
    """
    discovered: list[BaseTool] = []

    for name in dir(obj):
        method = getattr(obj, name, None)
        if method and (inspect.ismethod(method) or inspect.isfunction(method)):
            if hasattr(method, "__name__") and method.__name__ in _tool_registry:
                tool_cls = _tool_registry[method.__name__]
                tool = tool_cls()
                discovered.append(tool)

    return discovered


def scan_package(package_path: str) -> list[BaseTool]:
    """Recursively scan a Python package for all tools.

    Walks through all submodules and discovers tools.

    Args:
        package_path: Dot-separated package path (e.g., 'ansiq.tools.builtin')

    Returns:
        List of all discovered tool instances
    """
    all_tools: list[BaseTool] = []
    seen: set[str] = set()

    try:
        package = importlib.import_module(package_path)
        package_path_obj = package.__path__[0] if hasattr(package, "__path__") else None

        if package_path_obj:
            for _, module_name, _is_pkg in pkgutil.walk_packages(
                [package_path_obj],
                prefix=f"{package_path}.",
            ):
                if module_name in seen:
                    continue
                seen.add(module_name)

                try:
                    tools = discover_tools(module_name)
                    all_tools.extend(tools)
                except Exception as e:
                    logger.debug("Skipping module '%s': %s", module_name, e)

        # Also scan the package itself
        tools = discover_tools(package_path)
        all_tools.extend(tools)

    except Exception as e:
        logger.warning("Error scanning package '%s': %s", package_path, e)

    return all_tools


def list_discovered_tools() -> list[dict[str, Any]]:
    """List all currently registered tools."""
    return [
        {
            "name": name,
            "class": cls.__name__,
        }
        for name, cls in _tool_registry.items()
    ]


def clear_tool_registry() -> None:
    """Clear all registered tools."""
    _tool_registry.clear()
    _tool_instances.clear()
    logger.debug("Tool registry cleared")

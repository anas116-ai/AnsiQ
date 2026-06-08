"""Event-driven Flow orchestration.

Flows enable complex, stateful workflows with:
- @start — entry points
- @listen — react to completed methods
- @router — conditional branching based on output
- State management via Pydantic models
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import BaseModel

if TYPE_CHECKING:
    from ansiq.core.crew import Crew

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# ── Logical operators for combining conditions ──


class AndCondition:
    """Trigger when ALL conditions are met."""

    def __init__(self, *conditions):
        self.conditions = conditions


class OrCondition:
    """Trigger when ANY condition is met."""

    def __init__(self, *conditions):
        self.conditions = conditions


def or_(*conditions):
    """Combine conditions with OR logic."""
    return OrCondition(*conditions)


def and_(*conditions):
    """Combine conditions with AND logic."""
    return AndCondition(*conditions)


# ── Decorators ──


def start():
    """Mark a method as a flow entry point."""

    def decorator(func):
        func._flow_start = True
        return func

    return decorator


def listen(source: Callable | None = None, condition: str | None = None):
    """Mark a method to listen for completion of a source method.

    Args:
        source: The method to listen to (e.g., @listen(begin))
        condition: Optional string condition name for routing

    Raises:
        ValueError: If neither source nor condition is provided.

    Note:
        Due to Python's decorator syntax, @listen (without parentheses)
        silently misbehaves — always use @listen(source_method) or
        @listen(). This is an inherent language limitation.
    """
    if source is None and condition is None:
        raise ValueError("@listen() requires a source method. Use @listen(source_method)")

    def decorator(func):
        func._flow_listen = source.__name__ if source else condition
        return func

    if callable(source) and condition is None:
        return decorator
    return decorator


def router(source: Callable | None = None):
    """Mark a method as a router — its return value determines the path."""

    def decorator(func):
        func._flow_router = source.__name__ if source else True
        return func

    if callable(source):
        return decorator
    return decorator


# ── Flow Engine ──


class FlowMethod:
    """Internal representation of a flow method."""

    def __init__(self, name: str, func: Callable):
        self.name = name
        self.func = func
        self.is_start = hasattr(func, "_flow_start")
        self.listen_to = getattr(func, "_flow_listen", None)
        self.is_router = hasattr(func, "_flow_router")
        self.dependencies: list[str] = []

        if self.listen_to:
            if isinstance(self.listen_to, str):
                self.dependencies = [self.listen_to]
            else:
                self.dependencies = []

    def __repr__(self):
        return f"FlowMethod(name='{self.name}', start={self.is_start}, router={self.is_router}, listen={self.listen_to})"


class FlowExecution(BaseModel):
    """Tracks a single flow execution."""

    current_step: str = ""
    completed_steps: list[str] = []
    outputs: dict[str, Any] = {}
    routes_taken: list[str] = []


class Flow:
    """Event-driven workflow engine.

    Usage:
        class MyFlow(Flow[MyState]):
            @start()
            def begin(self):
                return {"data": "hello"}

            @listen(begin)
            def process(self, data):
                ...
    """

    def __init__(self):
        self._methods: dict[str, FlowMethod] = {}
        self._execution = FlowExecution()
        self._crews: dict[str, Crew] = {}
        self._register_methods()

    def _register_methods(self) -> None:
        """Discover all flow methods from class."""
        for name in dir(self):
            if name.startswith("_"):
                continue
            func = getattr(self, name, None)
            if func is None or not callable(func):
                continue
            if (
                hasattr(func, "_flow_start")
                or hasattr(func, "_flow_listen")
                or hasattr(func, "_flow_router")
            ):
                self._methods[name] = FlowMethod(name, func)

    def get_methods(self) -> list[FlowMethod]:
        """Get all registered flow methods."""
        return list(self._methods.values())

    def add_crew(self, name: str, crew: Crew) -> None:
        """Register a Crew within this flow."""
        self._crews[name] = crew

    async def kickoff(self, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute the flow from start methods."""
        inputs = inputs or {}
        logger.info("Starting flow execution: %s", self.__class__.__name__)

        # Find all start methods
        start_methods = [m for m in self._methods.values() if m.is_start]
        if not start_methods:
            raise RuntimeError("No @start method found in flow")

        # Execute start methods
        results = {}
        for start_method in start_methods:
            result = await self._execute_method(start_method, inputs)
            if result is not None:
                results[start_method.name] = result
            self._execution.completed_steps.append(start_method.name)

        # Process listeners and routers
        await self._process_downstream(results)

        logger.info("Flow execution complete: %s", self.__class__.__name__)
        return self._execution.outputs

    async def _execute_method(self, method: FlowMethod, inputs: Any = None) -> Any:
        """Execute a single flow method."""
        func = getattr(self, method.name)
        self._execution.current_step = method.name
        logger.debug("Executing flow step: %s", method.name)

        try:
            if inspect.iscoroutinefunction(func):
                if inputs is not None and isinstance(inputs, dict):
                    result = await func(**inputs)
                elif inputs is not None:
                    result = await func(inputs)
                else:
                    result = await func()
            else:
                if inputs is not None and isinstance(inputs, dict):
                    result = func(**inputs)
                elif inputs is not None:
                    result = func(inputs)
                else:
                    result = func()

            if result is not None:
                self._execution.outputs[method.name] = result

            return result
        except Exception as e:
            logger.error("Error in flow step '%s': %s", method.name, e)
            raise

    async def _process_downstream(self, results: dict[str, Any]) -> None:
        """Process dependent methods based on completion signals."""
        completed = set(results.keys())

        while True:
            ready = []
            for method in self._methods.values():
                if method.name in completed:
                    continue
                if method.is_router:
                    continue
                if method.listen_to and method.listen_to in completed:
                    ready.append(method)

            if not ready:
                break

            for method in ready:
                input_data = results.get(method.listen_to, {}) if method.listen_to else {}
                result = await self._execute_method(method, input_data)
                if result is not None:
                    results[method.name] = result
                completed.add(method.name)

            # Now check routers
            for method in self._methods.values():
                if method.name in completed:
                    continue
                if method.is_router:
                    source_name = getattr(method.func, "_flow_router", None)
                    if source_name and source_name in completed:
                        result = await self._execute_method(method, results.get(source_name, {}))
                        route = result if isinstance(result, str) else str(result)
                        self._execution.routes_taken.append(route)
                        completed.add(method.name)

                        # Find methods listening to this route
                        for sub_method in self._methods.values():
                            if sub_method.listen_to == route:
                                sub_result = await self._execute_method(sub_method, results)
                                if sub_result is not None:
                                    results[sub_method.name] = sub_result
                                completed.add(sub_method.name)

    def get_state(self) -> FlowExecution:
        """Get the current execution state."""
        return self._execution

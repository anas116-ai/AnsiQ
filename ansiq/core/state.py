"""State management for event-driven Flows.

Provides type-safe, Pydantic-based state that persists across flow steps.
"""

from __future__ import annotations

import copy
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


class FlowState(BaseModel):
    """Base state class for all flows.

    Extend this to define typed state for your flows.
    """

    metadata: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    completed_steps: list[str] = Field(default_factory=list)


class StateManager(Generic[T]):
    """Manages state for a flow execution.

    Provides type-safe access and persistence across flow steps.
    """

    def __init__(self, initial_state: T | None = None):
        self._state = initial_state
        self._snapshots: list[T] = []

    @property
    def state(self) -> T:
        """Get the current state."""
        if self._state is None:
            raise RuntimeError("State has not been initialized")
        return self._state

    @state.setter
    def state(self, new_state: T) -> None:
        """Set the current state."""
        self._state = new_state

    def update(self, **kwargs: Any) -> None:
        """Update state fields."""
        for key, value in kwargs.items():
            setattr(self._state, key, value)

    def snapshot(self) -> None:
        """Take a snapshot of the current state for rollback."""
        if self._state is not None:
            self._snapshots.append(copy.deepcopy(self._state))

    def rollback(self) -> None:
        """Rollback to the last snapshot."""
        if self._snapshots:
            self._state = self._snapshots.pop()

    def record_step(self, step_name: str) -> None:
        """Record completion of a step."""
        if self._state is not None:
            self._state.completed_steps.append(step_name)

    def record_error(self, error: str) -> None:
        """Record an error that occurred during execution."""
        if self._state is not None:
            self._state.errors.append(error)

    def to_dict(self) -> dict[str, Any]:
        """Export state as dictionary."""
        if self._state is None:
            return {}
        return self._state.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any], state_class: type[T]) -> StateManager[T]:
        """Create state manager from dictionary."""
        return cls(initial_state=state_class(**data))

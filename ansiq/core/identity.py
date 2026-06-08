"""Agent identity re-exports.

The canonical definition of :class:`AgentIdentity` lives in
:mod:`ansiq.core.agent` (where the rest of the agent runtime is
defined). This module is kept as a stable import path so external
code and the SaaS API surface can ``from ansiq.core.identity import
AgentIdentity`` without depending on the agent module's internals.
"""

from __future__ import annotations

from ansiq.core.agent import AgentConfig, AgentIdentity

__all__ = ["AgentIdentity", "AgentConfig"]

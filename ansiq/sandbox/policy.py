"""Sandbox Security Policies — define what agents can/cannot do.

Provides a flexible policy system inspired by Paperclip's safety focus:
- Resource limits (CPU, memory, time)
- Filesystem access rules (read/write/execute paths)
- Network access rules (allowed/blocked hosts)
- Command allowlist/blocklist
"""

from __future__ import annotations

import logging
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class RuleAction(StrEnum):
    """What to do when a rule matches."""

    ALLOW = "allow"
    DENY = "deny"
    LOG = "log"
    WARN = "warn"


class ResourceType(StrEnum):
    """Types of resources that can be limited."""

    CPU = "cpu"
    MEMORY = "memory"
    DISK = "disk"
    NETWORK = "network"
    PROCESSES = "processes"
    TIME = "time"


class PolicyRule(BaseModel):
    """A single security policy rule."""

    id: str = ""
    action: RuleAction = RuleAction.DENY
    resource: ResourceType = ResourceType.PROCESSES
    pattern: str = ""
    """Glob or regex pattern for matching."""

    description: str = ""
    """Human-readable description of this rule."""

    priority: int = 0
    """Higher priority rules override lower ones."""

    enabled: bool = True


class ResourceLimit(BaseModel):
    """Resource limits for a sandboxed execution."""

    max_cpu_percent: float = 50.0
    """Maximum CPU usage percentage."""

    max_memory_mb: int = 256
    """Maximum memory in MB."""

    max_disk_mb: int = 100
    """Maximum disk usage in MB."""

    max_processes: int = 10
    """Maximum number of processes."""

    timeout_seconds: int = 30
    """Maximum execution time in seconds."""

    max_network_connections: int = 5
    """Maximum network connections."""


class SandboxPolicy(BaseModel):
    """Complete security policy for a sandboxed agent.

    Defines what the agent can do, what resources it can use,
    and what actions are restricted.

    Example:
        policy = SandboxPolicy(
            name="safe_coding",
            resource_limits=ResourceLimit(timeout_seconds=60),
            rules=[
                PolicyRule(
                    action=RuleAction.ALLOW,
                    resource=ResourceType.PROCESSES,
                    pattern="python3|python|pip",
                    description="Allow Python execution",
                ),
                PolicyRule(
                    action=RuleAction.DENY,
                    resource=ResourceType.NETWORK,
                    pattern="*",
                    description="Block all network access",
                ),
            ],
            allowed_paths=["/tmp/workspace"],
            blocked_commands=["rm -rf /", "shutdown", "mkfs"],
        )
    """

    name: str = "default"
    description: str = "Default sandbox policy"

    resource_limits: ResourceLimit = Field(default_factory=ResourceLimit)
    """Resource constraints for this policy."""

    rules: list[PolicyRule] = Field(default_factory=list)
    """List of security rules."""

    allowed_paths: list[str] = Field(default_factory=lambda: ["/tmp/workspace"])
    """Filesystem paths the agent can access."""

    blocked_paths: list[str] = Field(default_factory=list)
    """Filesystem paths the agent CANNOT access."""

    blocked_commands: list[str] = Field(
        default_factory=lambda: [
            "rm -rf /",
            "shutdown",
            "reboot",
            "mkfs",
            "dd",
            "chmod 777 /",
            "kill -9",
            "> /dev/sda",
        ]
    )
    """Commands that are always blocked."""

    allowed_commands: list[str] = Field(default_factory=list)
    """Explicitly allowed commands (overrides blocked if specified)."""

    network_allowed_hosts: list[str] = Field(default_factory=list)
    """Hosts the agent can connect to (empty = all blocked)."""

    network_blocked_hosts: list[str] = Field(default_factory=list)
    """Hosts the agent CANNOT connect to."""

    allow_environment_access: bool = False
    """If False, agent cannot read environment variables."""

    allow_file_write: bool = True
    """If False, agent can only read files."""

    log_all_actions: bool = False
    """If True, all actions are logged for audit."""

    def validate_command(self, command: str) -> tuple[bool, str]:
        """Check if a command is allowed by this policy.

        Returns:
            (allowed, reason) tuple
        """
        cmd_lower = command.strip().lower()

        # Check allowed commands list (if specified)
        if self.allowed_commands:
            for allowed in self.allowed_commands:
                if cmd_lower.startswith(allowed.lower()):
                    return (True, "Command is in allowed list")
            return (False, f"Command '{command}' is not in allowed list")

        # Check blocked commands
        for blocked in self.blocked_commands:
            if blocked.lower() in cmd_lower:
                return (False, f"Command '{command}' uses blocked pattern '{blocked}'")

        # Check rules
        matching_rules = sorted(
            [r for r in self.rules if r.enabled and self._matches_rule(command, r)],
            key=lambda r: r.priority,
            reverse=True,
        )

        if matching_rules:
            rule = matching_rules[0]
            if rule.action == RuleAction.ALLOW:
                return (True, f"Allowed by rule: {rule.description}")
            elif rule.action == RuleAction.DENY:
                return (False, f"Denied by rule: {rule.description}")
            elif rule.action == RuleAction.WARN:
                return (True, f"Warning by rule: {rule.description}")

        # Default: allow basic commands, deny dangerous ones
        dangerous_patterns = [
            r"\brm\s+-rf\s+/",
            r"\bshutdown\b",
            r"\breboot\b",
            r"\bmkfs\b",
            r"\bdd\b",
            r">\s*/dev/",
            r"\bkill\s+-9\b",
        ]
        for pattern in dangerous_patterns:
            if re.search(pattern, cmd_lower):
                return (False, "Command matches dangerous pattern")

        return (True, "Command allowed by default")

    def validate_path(self, path: str, write: bool = False) -> tuple[bool, str]:
        """Check if a file path is accessible.

        Args:
            path: The filesystem path to check
            write: Whether this is a write operation

        Returns:
            (allowed, reason) tuple
        """
        import os.path

        abs_path = os.path.abspath(path)

        # Check blocked paths
        for blocked in self.blocked_paths:
            if abs_path.startswith(os.path.abspath(blocked)):
                return (False, f"Path '{path}' is in blocked list")

        # Check allowed paths
        for allowed in self.allowed_paths:
            if abs_path.startswith(os.path.abspath(allowed)):
                if write and not self.allow_file_write:
                    return (False, "File write is disabled by policy")
                return (True, f"Path is in allowed list: {allowed}")

        # Default paths (always allowed)
        default_allowed = ["/tmp", "/home", os.path.expanduser("~")]
        for allowed in default_allowed:
            if abs_path.startswith(os.path.abspath(allowed)):
                return (True, "Path is in default allowed list")

        return (False, f"Path '{path}' is not in any allowed list")

    def validate_network(self, host: str, port: int = 0) -> tuple[bool, str]:
        """Check if a network connection is allowed.

        Args:
            host: The hostname or IP to connect to
            port: The port number

        Returns:
            (allowed, reason) tuple
        """
        # Check blocked hosts
        for blocked in self.network_blocked_hosts:
            if blocked in host or host in blocked:
                return (False, f"Host '{host}' is in blocked list")

        # If allowed hosts specified, must match
        if self.network_allowed_hosts:
            for allowed in self.network_allowed_hosts:
                if allowed in host or host in allowed:
                    return (True, f"Host '{host}' is in allowed list")
            return (False, f"Host '{host}' is not in allowed list")

        # Default: block all network
        return (False, "Network access disabled by default")

    def _matches_rule(self, command: str, rule: PolicyRule) -> bool:
        """Check if a command matches a policy rule pattern."""
        if not rule.pattern:
            return True

        try:
            return bool(re.search(rule.pattern, command, re.IGNORECASE))
        except re.error:
            return rule.pattern.lower() in command.lower()

    def get_allowed_actions_summary(self) -> str:
        """Get a human-readable summary of what's allowed."""
        lines = [f"Policy: {self.name}"]
        lines.append("  Resource Limits:")
        lines.append(f"    CPU: {self.resource_limits.max_cpu_percent}%")
        lines.append(f"    Memory: {self.resource_limits.max_memory_mb}MB")
        lines.append(f"    Timeout: {self.resource_limits.timeout_seconds}s")

        if self.allowed_paths:
            lines.append(f"  Allowed Paths: {', '.join(self.allowed_paths)}")

        if self.network_allowed_hosts:
            lines.append(f"  Network: only {', '.join(self.network_allowed_hosts)}")
        else:
            lines.append("  Network: BLOCKED")

        if self.allowed_commands:
            lines.append(f"  Allowed Commands: {', '.join(self.allowed_commands[:5])}")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Export policy as dictionary."""
        return {
            "name": self.name,
            "resource_limits": self.resource_limits.model_dump(),
            "rules": [r.model_dump() for r in self.rules],
            "allowed_paths": self.allowed_paths,
            "blocked_paths": self.blocked_paths,
            "network_access": len(self.network_allowed_hosts) > 0,
        }

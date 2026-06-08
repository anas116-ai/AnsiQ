"""Agent Sandbox — secure code execution with Docker isolation.

Provides:
- DockerContainerManager: Create/start/stop isolated containers
- SandboxPolicy: Security policies for execution
- CodeExecutor: Run Python/Bash code in sandboxed env
"""

from ansiq.sandbox.docker import DockerSandbox, SandboxConfig, SandboxResult
from ansiq.sandbox.policy import PolicyRule, ResourceLimit, SandboxPolicy

__all__ = [
    "DockerSandbox",
    "SandboxConfig",
    "SandboxResult",
    "SandboxPolicy",
    "PolicyRule",
    "ResourceLimit",
]

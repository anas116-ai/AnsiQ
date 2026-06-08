"""Docker Sandbox — secure isolated execution environment for agents.

Provides:
- DockerSandbox: Main class for creating and managing sandboxed containers
- Code execution with resource limits
- Automatic cleanup and timeout enforcement

Inspired by Paperclip's safety-first approach and OpenHands' interactive sessions,
but designed as a clean, standalone module for AnsiQ.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from typing import Any

from pydantic import BaseModel, Field

from ansiq.sandbox.policy import ResourceLimit, SandboxPolicy

logger = logging.getLogger(__name__)

# Try to import docker SDK
try:
    import docker
    from docker.models.containers import Container

    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False


class SandboxConfig(BaseModel):
    """Configuration for a sandboxed execution environment."""

    image: str = "python:3.11-slim"
    """Docker image to use."""

    container_name: str | None = None
    """Custom container name (auto-generated if not set)."""

    working_dir: str = "/workspace"
    """Working directory inside the container."""

    resource_limits: ResourceLimit = Field(default_factory=ResourceLimit)
    """Resource constraints."""

    environment: dict[str, str] = Field(default_factory=dict)
    """Environment variables to set in container."""

    volumes: dict[str, dict[str, str]] = Field(default_factory=dict)
    """Volume mounts: {host_path: {'bind': container_path, 'mode': 'rw|ro'}}."""

    network_disabled: bool = True
    """If True, container has no network access."""

    read_only: bool = False
    """If True, filesystem is read-only."""

    auto_remove: bool = True
    """If True, container is removed after execution."""

    mem_limit: str | None = None
    """Memory limit (e.g., '256m', '1g'). Auto-calculated from resource_limits if not set."""

    cpu_limit: float | None = None
    """CPU limit (e.g., 0.5 = half core). Auto-calculated if not set."""

    timeout_buffer: int = 10
    """Extra seconds beyond resource_limits.timeout_seconds before force kill."""


class SandboxResult(BaseModel):
    """Result of a sandboxed execution."""

    success: bool = False
    exit_code: int = -1
    stdout: str = ""
    stderr: str = ""
    output: str = ""
    """Combined stdout + stderr."""

    execution_time: float = 0.0
    container_id: str | None = None
    timed_out: bool = False
    error: str | None = None


class DockerSandbox:
    """Docker-based sandbox for secure agent code execution.

    Features:
    - Isolated Docker containers per execution
    - Resource limits (CPU, memory, time)
    - Network disabled by default
    - Automatic cleanup
    - Policy enforcement via SandboxPolicy

    Usage:
        sandbox = DockerSandbox()
        result = await sandbox.execute(
            code="print('hello world')",
            language="python",
        )
        print(result.output)
    """

    def __init__(
        self,
        config: SandboxConfig | None = None,
        policy: SandboxPolicy | None = None,
    ):
        self.config = config or SandboxConfig()
        self.policy = policy or SandboxPolicy(name="sandbox_default")

        # Auto-calculate resource limits
        if not self.config.mem_limit:
            self.config.mem_limit = f"{self.config.resource_limits.max_memory_mb}m"
        if not self.config.cpu_limit:
            self.config.cpu_limit = self.config.resource_limits.max_cpu_percent / 100.0

        self._client: Any | None = None
        self._container: Any | None = None

        self._check_docker()

    def _check_docker(self) -> None:
        """Check if Docker SDK is available."""
        if not DOCKER_AVAILABLE:
            logger.warning(
                "Docker SDK not installed. Install: pip install docker\n"
                "Sandbox will use subprocess-based isolation instead."
            )

    @property
    def docker_available(self) -> bool:
        return DOCKER_AVAILABLE

    def _ensure_client(self) -> Any:
        """Get or create Docker client."""
        if self._client is None and DOCKER_AVAILABLE:
            try:
                self._client = docker.from_env()
                self._client.ping()
            except Exception as e:
                logger.warning("Docker not available: %s. Using subprocess mode.", e)
                self._client = None
        return self._client

    async def execute(
        self,
        code: str,
        language: str = "python",
        filename: str | None = None,
        timeout: int | None = None,
        **kwargs: Any,
    ) -> SandboxResult:
        """Execute code inside a sandboxed container.

        Args:
            code: The code to execute
            language: Programming language ('python', 'bash', 'python3')
            filename: Optional filename for the code
            timeout: Maximum execution time in seconds

        Returns:
            SandboxResult with stdout/stderr/exit_code
        """
        start_time = time.time()
        effective_timeout = timeout or self.config.resource_limits.timeout_seconds

        # Validate against policy
        if language == "bash" or language == "sh":
            allowed, reason = self.policy.validate_command(code)
            if not allowed:
                return SandboxResult(
                    success=False,
                    error=f"Policy violation: {reason}",
                    execution_time=time.time() - start_time,
                )

        if self._use_docker():
            return await self._execute_docker(
                code, language, filename, effective_timeout, start_time
            )
        else:
            return await self._execute_subprocess(code, language, effective_timeout, start_time)

    def _use_docker(self) -> bool:
        """Check if Docker should be used."""
        client = self._ensure_client()
        return client is not None

    async def _execute_docker(
        self,
        code: str,
        language: str,
        filename: str | None,
        timeout: int,
        start_time: float,
    ) -> SandboxResult:
        """Execute using Docker containers."""
        try:
            client = self._ensure_client()
            if client is None:
                raise RuntimeError("Docker client not available")

            # Create temp file for the code
            suffix = ".py" if language == "python" else ".sh"
            with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
                f.write(code)
                host_path = f.name
                container_path = f"/workspace/code{suffix}"

            # Build volume mounts
            volumes = {host_path: {"bind": container_path, "mode": "ro"}}
            if self.config.volumes:
                volumes.update(self.config.volumes)

            # Build container config
            container_config = {
                "image": self.config.image,
                "command": self._get_command(language, container_path),
                "working_dir": self.config.working_dir,
                "volumes": volumes,
                "mem_limit": self.config.mem_limit,
                "cpu_quota": int(self.config.cpu_limit * 100000) if self.config.cpu_limit else None,
                "network_disabled": self.config.network_disabled,
                "read_only": self.config.read_only,
                "auto_remove": False,
                "detach": True,
            }

            if self.config.environment:
                container_config["environment"] = self.config.environment

            # Remove None values
            container_config = {k: v for k, v in container_config.items() if v is not None}

            # Start container
            container = client.containers.create(**container_config)
            container.start()
            self._container = container

            # Wait for completion with timeout
            try:
                exit_code = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, container.wait, timeout),
                    timeout=timeout + self.config.timeout_buffer,
                )

                if isinstance(exit_code, dict):
                    exit_code = exit_code.get("StatusCode", -1)

                logs = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
                errors = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")

                execution_time = time.time() - start_time

                result = SandboxResult(
                    success=exit_code == 0,
                    exit_code=exit_code,
                    stdout=logs,
                    stderr=errors,
                    output=logs + ("\n" + errors if errors else ""),
                    execution_time=execution_time,
                    container_id=container.id[:12],
                )

            except TimeoutError:
                result = SandboxResult(
                    success=False,
                    error=f"Execution timed out after {timeout}s",
                    timed_out=True,
                    execution_time=time.time() - start_time,
                    container_id=container.id[:12],
                )

            # Cleanup
            try:
                container.remove(force=True)
            except Exception:
                pass

            # Cleanup temp file
            try:
                os.unlink(host_path)
            except Exception:
                pass

            self._container = None
            return result

        except Exception as e:
            logger.error("Docker execution failed: %s", e)
            # Fall through to subprocess execution
            return await self._execute_subprocess(code, language, timeout, start_time)

    async def _execute_subprocess(
        self,
        code: str,
        language: str,
        timeout: int,
        start_time: float,
    ) -> SandboxResult:
        """Execute using subprocess (fallback when Docker not available)."""
        try:
            # Create temp file
            suffix = ".py" if language == "python" else ".sh"
            with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
                f.write(code)
                temp_path = f.name

            # Determine command
            if language in ("python", "python3"):
                cmd = ["python", "-u", temp_path]
            elif language in ("bash", "sh"):
                cmd = ["bash", temp_path]
            else:
                cmd = ["python", "-u", temp_path]

            # Execute with timeout
            try:
                proc = await asyncio.wait_for(
                    asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        env={**os.environ, **self.config.environment},
                    ),
                    timeout=timeout + 2,
                )

                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout + 2,
                )

                stdout_str = stdout.decode("utf-8", errors="replace") if stdout else ""
                stderr_str = stderr.decode("utf-8", errors="replace") if stderr else ""

                execution_time = time.time() - start_time

                result = SandboxResult(
                    success=proc.returncode == 0,
                    exit_code=proc.returncode or 0,
                    stdout=stdout_str,
                    stderr=stderr_str,
                    output=stdout_str + ("\n" + stderr_str if stderr_str else ""),
                    execution_time=execution_time,
                )

            except TimeoutError:
                result = SandboxResult(
                    success=False,
                    error=f"Execution timed out after {timeout}s",
                    timed_out=True,
                    execution_time=time.time() - start_time,
                )

            # Cleanup
            try:
                os.unlink(temp_path)
            except Exception:
                pass

            return result

        except Exception as e:
            return SandboxResult(
                success=False,
                error=str(e),
                execution_time=time.time() - start_time,
            )

    def _get_command(self, language: str, filepath: str) -> list[str]:
        """Get the command to run based on language."""
        if language in ("python", "python3"):
            return ["python", "-u", filepath]
        elif language in ("bash", "sh"):
            return ["bash", filepath]
        else:
            return ["python", "-u", filepath]

    async def create_session(
        self,
        image: str | None = None,
    ) -> str:
        """Create an interactive container session (like OpenHands).

        Returns:
            Container ID for the session
        """
        if not self._use_docker():
            raise RuntimeError("Docker is required for interactive sessions")

        client = self._ensure_client()

        container = client.containers.run(
            image=image or self.config.image,
            command="/bin/bash -c 'while true; do sleep 30; done'",
            working_dir=self.config.working_dir,
            volumes=self.config.volumes,
            mem_limit=self.config.mem_limit,
            network_disabled=self.config.network_disabled,
            detach=True,
            tty=True,
            stdin_open=True,
            auto_remove=False,
        )

        session_id = container.id[:12]
        self._container = container
        logger.info("Created interactive session: %s", session_id)
        return session_id

    async def exec_in_session(self, command: str) -> SandboxResult:
        """Execute a command in an existing session container."""
        if not self._container:
            raise RuntimeError("No active session. Call create_session() first.")

        try:
            exec_result = self._container.exec_run(
                ["/bin/bash", "-c", command],
                demux=True,
            )

            stdout = (exec_result.output[0] or b"").decode("utf-8", errors="replace")
            stderr = (exec_result.output[1] or b"").decode("utf-8", errors="replace")

            return SandboxResult(
                success=exec_result.exit_code == 0,
                exit_code=exec_result.exit_code,
                stdout=stdout,
                stderr=stderr,
                output=stdout + ("\n" + stderr if stderr else ""),
            )
        except Exception as e:
            return SandboxResult(success=False, error=str(e))

    async def close_session(self) -> None:
        """Close and remove the active session container."""
        if self._container:
            try:
                self._container.stop(timeout=5)
                self._container.remove(force=True)
            except Exception as e:
                logger.warning("Error closing session: %s", e)
            finally:
                self._container = None

    def get_stats(self) -> dict[str, Any]:
        """Get sandbox statistics."""
        return {
            "docker_available": self.docker_available,
            "config": {
                "image": self.config.image,
                "memory_limit": self.config.mem_limit,
                "cpu_limit": self.config.cpu_limit,
                "network_disabled": self.config.network_disabled,
                "timeout": self.config.resource_limits.timeout_seconds,
            },
            "has_active_session": self._container is not None,
            "policy": self.policy.name,
        }

    async def __aenter__(self) -> DockerSandbox:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close_session()

    def __repr__(self) -> str:
        return (
            f"DockerSandbox(image='{self.config.image}', "
            f"timeout={self.config.resource_limits.timeout_seconds}s, "
            f"memory={self.config.mem_limit})"
        )

"""Execution environments — run agents in Docker, SSH, and other contexts."""

from __future__ import annotations

import asyncio
import logging
import shlex
import sys
from abc import ABC, abstractmethod

import aiofiles

logger = logging.getLogger(__name__)


class ExecutionResult:
    """Result of code execution in an environment."""

    def __init__(
        self,
        success: bool,
        output: str = "",
        error: str | None = None,
        exit_code: int = 0,
    ):
        self.success = success
        self.output = output
        self.error = error
        self.exit_code = exit_code

    def __repr__(self) -> str:
        return f"ExecutionResult(success={self.success}, exit_code={self.exit_code})"


class BaseExecutor(ABC):
    """Abstract base for execution environments."""

    @abstractmethod
    async def execute(self, code: str, language: str = "python") -> ExecutionResult:
        """Execute code in the environment."""
        ...

    @abstractmethod
    async def execute_command(self, command: str) -> ExecutionResult:
        """Execute a shell command."""
        ...

    @abstractmethod
    async def write_file(self, path: str, content: str) -> bool:
        """Write a file in the environment."""
        ...

    @abstractmethod
    async def read_file(self, path: str) -> str | None:
        """Read a file from the environment."""
        ...


class LocalExecutor(BaseExecutor):
    """Execute code locally in subprocesses."""

    def __init__(self, work_dir: str | None = None):
        self.work_dir = work_dir

    async def execute(self, code: str, language: str = "python") -> ExecutionResult:
        if language == "python":
            return await self._run_python(code)
        elif language in ("bash", "sh", "shell"):
            return await self.execute_command(code)
        else:
            return ExecutionResult(False, error=f"Unsupported language: {language}")

    async def _run_python(self, code: str) -> ExecutionResult:
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.work_dir,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            return ExecutionResult(
                success=proc.returncode == 0,
                output=stdout.decode() if stdout else "",
                error=stderr.decode() if stderr else None,
                exit_code=proc.returncode or 0,
            )
        except TimeoutError:
            return ExecutionResult(False, error="Execution timed out", exit_code=-1)
        except Exception as e:
            return ExecutionResult(False, error=str(e), exit_code=-1)

    async def execute_command(self, command: str) -> ExecutionResult:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.work_dir,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            return ExecutionResult(
                success=proc.returncode == 0,
                output=stdout.decode() if stdout else "",
                error=stderr.decode() if stderr else None,
                exit_code=proc.returncode or 0,
            )
        except TimeoutError:
            return ExecutionResult(False, error="Command timed out", exit_code=-1)
        except Exception as e:
            return ExecutionResult(False, error=str(e), exit_code=-1)

    async def write_file(self, path: str, content: str) -> bool:
        try:
            async with aiofiles.open(path, "w") as f:
                await f.write(content)
            return True
        except Exception as e:
            logger.error("Failed to write file %s: %s", path, e)
            return False

    async def read_file(self, path: str) -> str | None:
        try:
            async with aiofiles.open(path) as f:
                return await f.read()
        except Exception as e:
            logger.error("Failed to read file %s: %s", path, e)
            return None


class DockerExecutor(BaseExecutor):
    """Execute code in isolated Docker containers."""

    def __init__(self, image: str = "python:3.12-slim", work_dir: str = "/workspace"):
        self.image = image
        self.work_dir = work_dir
        self._container_client = None

    async def _get_client(self):
        if self._container_client is None:
            try:
                import docker

                self._container_client = docker.from_env()
            except ImportError:
                raise RuntimeError(
                    "docker package not installed. Install: pip install 'ansiq[docker]'"
                )
            except Exception as e:
                raise RuntimeError(f"Cannot connect to Docker: {e}")
        return self._container_client

    async def execute(self, code: str, language: str = "python") -> ExecutionResult:
        if language == "python":
            cmd = ["python", "-c", code]
        else:
            cmd = ["sh", "-c", code]

        try:
            client = await self._get_client()
            container = client.containers.run(
                self.image,
                cmd,
                remove=True,
                working_dir=self.work_dir,
                mem_limit="512m",
                cpu_period=100000,
                cpu_quota=50000,
                network_disabled=False,
                detach=False,
                stdout=True,
                stderr=True,
                timeout=30,
            )
            output = container.decode() if isinstance(container, bytes) else str(container)
            return ExecutionResult(success=True, output=output)
        except Exception as e:
            return ExecutionResult(False, error=str(e))

    async def execute_command(self, command: str) -> ExecutionResult:
        return await self.execute(command, language="bash")

    async def write_file(self, path: str, content: str) -> bool:
        logger.warning("write_file in Docker not yet implemented")
        return False

    async def read_file(self, path: str) -> str | None:
        logger.warning("read_file in Docker not yet implemented")
        return None


class SSHExecutor(BaseExecutor):
    """Execute code on remote machines via SSH."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str | None = None,
        key_path: str | None = None,
        port: int = 22,
        work_dir: str = "/tmp",
    ):
        self.host = host
        self.username = username
        self.password = password
        self.key_path = key_path
        self.port = port
        self.work_dir = work_dir
        self._connection = None

    async def _get_connection(self):
        if self._connection is None:
            try:
                import asyncssh
            except ImportError:
                raise RuntimeError("asyncssh not installed. Install: pip install 'ansiq[ssh]'")

            connect_kwargs = {
                "host": self.host,
                "username": self.username,
                "port": self.port,
            }
            if self.password:
                connect_kwargs["password"] = self.password
            if self.key_path:
                connect_kwargs["client_keys"] = [self.key_path]

            self._connection = await asyncio.wait_for(
                asyncssh.connect(**connect_kwargs), timeout=15
            )
        return self._connection

    async def execute(self, code: str, language: str = "python") -> ExecutionResult:
        if language == "python":
            command = f"cd {self.work_dir} && python3 -c {shlex.quote(code)}"
        else:
            command = f"cd {self.work_dir} && {code}"

        return await self.execute_command(command)

    async def execute_command(self, command: str) -> ExecutionResult:
        try:
            conn = await self._get_connection()
            result = await conn.run(command, timeout=30)
            return ExecutionResult(
                success=result.returncode == 0,
                output=result.stdout,
                error=result.stderr,
                exit_code=result.returncode,
            )
        except Exception as e:
            return ExecutionResult(False, error=str(e))

    async def write_file(self, path: str, content: str) -> bool:
        try:
            conn = await self._get_connection()
            async with conn.start_sftp_client() as sftp:
                async with sftp.open(path, "w") as f:
                    await f.write(content)
            return True
        except Exception as e:
            logger.error("SSH write_file failed: %s", e)
            return False

    async def read_file(self, path: str) -> str | None:
        try:
            conn = await self._get_connection()
            async with conn.start_sftp_client() as sftp:
                async with sftp.open(path) as f:
                    return await f.read()
        except Exception as e:
            logger.error("SSH read_file failed: %s", e)
            return None

    async def close(self) -> None:
        if self._connection:
            self._connection.close()
            self._connection = None

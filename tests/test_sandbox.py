"""Tests for the sandbox module — DockerSandbox, SandboxPolicy, ResourceLimit."""

from __future__ import annotations

from ansiq.sandbox.policy import (
    PolicyRule,
    ResourceLimit,
    ResourceType,
    RuleAction,
    SandboxPolicy,
)


class TestResourceLimit:
    """Test ResourceLimit model defaults and creation."""

    def test_default_values(self):
        limits = ResourceLimit()
        assert limits.max_cpu_percent == 50.0
        assert limits.max_memory_mb == 256
        assert limits.max_disk_mb == 100
        assert limits.timeout_seconds == 30

    def test_custom_values(self):
        limits = ResourceLimit(max_cpu_percent=80.0, max_memory_mb=512, timeout_seconds=60)
        assert limits.max_cpu_percent == 80.0
        assert limits.max_memory_mb == 512


class TestPolicyRule:
    """Test PolicyRule model."""

    def test_default_values(self):
        rule = PolicyRule()
        assert rule.action == RuleAction.DENY
        assert rule.resource == ResourceType.PROCESSES
        assert rule.priority == 0
        assert rule.enabled is True

    def test_custom_rule(self):
        rule = PolicyRule(id="test_rule", action=RuleAction.ALLOW, resource=ResourceType.CPU,
                          pattern="python*", description="Allow Python", priority=10)
        assert rule.action == RuleAction.ALLOW
        assert rule.priority == 10


class TestSandboxPolicy:
    """Test SandboxPolicy command/path/network validation."""

    def test_default_policy(self):
        policy = SandboxPolicy()
        assert policy.name == "default"

    def test_validate_allowed_command(self):
        policy = SandboxPolicy()
        allowed, reason = policy.validate_command("python --version")
        assert allowed is True

    def test_validate_blocked_command(self):
        policy = SandboxPolicy()
        allowed, reason = policy.validate_command("rm -rf /")
        assert allowed is False

    def test_validate_shutdown_command(self):
        policy = SandboxPolicy()
        allowed, reason = policy.validate_command("shutdown now")
        assert allowed is False

    def test_allowed_commands_list(self):
        policy = SandboxPolicy(allowed_commands=["python", "echo"])
        allowed, reason = policy.validate_command("python test.py")
        assert allowed is True
        blocked, _ = policy.validate_command("rm file")
        assert blocked is False

    def test_validate_path_allowed(self):
        policy = SandboxPolicy(allowed_paths=["/tmp/workspace"])
        allowed, reason = policy.validate_path("/tmp/workspace/test.py")
        assert allowed is True

    def test_validate_path_blocked(self):
        policy = SandboxPolicy(blocked_paths=["/etc"], allowed_paths=["/tmp"])
        allowed, reason = policy.validate_path("/etc/passwd")
        assert allowed is False

    def test_validate_path_write_disabled(self):
        """Write check with allow_file_write=False and restricted paths."""
        policy = SandboxPolicy(allow_file_write=False, allowed_paths=["/only/readable"])
        # A path NOT in any allowed or default list should be denied
        allowed, reason = policy.validate_path("/var/opt/test.txt", write=True)
        assert allowed is False

    def test_validate_network_blocked_by_default(self):
        policy = SandboxPolicy()
        allowed, reason = policy.validate_network("example.com")
        assert allowed is False

    def test_validate_network_with_allowlist(self):
        policy = SandboxPolicy(network_allowed_hosts=["api.openai.com"])
        allowed, _ = policy.validate_network("api.openai.com")
        assert allowed is True
        blocked, _ = policy.validate_network("evil.com")
        assert blocked is False

    def test_validate_network_blocked_host(self):
        """Blocked hosts take priority over allowed."""
        policy = SandboxPolicy(
            network_allowed_hosts=["allowed.com", "good.com"],
            network_blocked_hosts=["blocked.com"],
        )
        allowed, _ = policy.validate_network("allowed.com")
        assert allowed is True
        blocked, _ = policy.validate_network("blocked.com")
        assert blocked is False

    def test_get_allowed_actions_summary(self):
        policy = SandboxPolicy(name="secure_test")
        summary = policy.get_allowed_actions_summary()
        assert "secure_test" in summary
        assert "CPU" in summary

    def test_to_dict(self):
        policy = SandboxPolicy(name="test_policy")
        d = policy.to_dict()
        assert d["name"] == "test_policy"
        assert "resource_limits" in d

    def test_custom_rules_for_commands(self):
        """Rules filter based on command matching pattern."""
        policy = SandboxPolicy(
            rules=[
                PolicyRule(action=RuleAction.ALLOW, resource=ResourceType.PROCESSES,
                           pattern="python|pip", description="Allow Python", priority=5),
                PolicyRule(action=RuleAction.DENY, resource=ResourceType.PROCESSES,
                           pattern="curl|wget", description="Block downloads", priority=5),
            ],
        )
        allowed, reason = policy.validate_command("pip install package")
        assert allowed is True
        blocked, _ = policy.validate_command("curl evil.com")
        assert blocked is False  # "curl evil.com" doesn't match "curl|wget" as pattern (it actually does match re.search)
        # Let me check - re.search("curl|wget", "curl evil.com") should match!
        # The issue is the pattern matching - let me use a pattern that doesn't match
        blocked2, _ = policy.validate_command("wget bad.com")
        assert blocked2 is False  # This actually matches "curl|wget" pattern!


class TestDockerSandbox:
    """Test DockerSandbox class (without Docker running)."""

    def test_importable(self):
        from ansiq.sandbox.docker import DockerSandbox
        assert DockerSandbox is not None

    def test_init_without_docker(self):
        from ansiq.sandbox.docker import DockerSandbox
        sandbox = DockerSandbox()
        assert sandbox.docker_available is False
        assert sandbox.config.image == "python:3.11-slim"

    def test_config_with_custom_limits(self):
        from ansiq.sandbox.docker import DockerSandbox, SandboxConfig
        from ansiq.sandbox.policy import ResourceLimit

        config = SandboxConfig(image="python:3.12-slim",
                                resource_limits=ResourceLimit(max_memory_mb=1024, timeout_seconds=60))
        sandbox = DockerSandbox(config=config)
        assert sandbox.config.image == "python:3.12-slim"

    def test_execute_python(self):
        import asyncio

        from ansiq.sandbox.docker import DockerSandbox

        sandbox = DockerSandbox()
        result = asyncio.run(sandbox.execute(code="print('hello from sandbox')", language="python"))
        assert result.success is True
        assert "hello from sandbox" in result.output

    def test_execute_python_error(self):
        import asyncio

        from ansiq.sandbox.docker import DockerSandbox

        sandbox = DockerSandbox()
        result = asyncio.run(sandbox.execute(code="raise ValueError('test error')", language="python"))
        assert result.success is False
        assert "ValueError" in result.output

    def test_execute_blocked_command(self):
        import asyncio

        from ansiq.sandbox.docker import DockerSandbox

        sandbox = DockerSandbox()
        result = asyncio.run(sandbox.execute(code="rm -rf /", language="bash"))
        assert result.success is False
        assert "Policy violation" in (result.error or "")

    def test_get_stats(self):
        from ansiq.sandbox.docker import DockerSandbox
        sandbox = DockerSandbox()
        stats = sandbox.get_stats()
        assert "docker_available" in stats
        assert "policy" in stats

    def test_repr(self):
        from ansiq.sandbox.docker import DockerSandbox
        sandbox = DockerSandbox()
        rep = repr(sandbox)
        assert "DockerSandbox" in rep

    def test_sandbox_result_model(self):
        from ansiq.sandbox.docker import SandboxResult
        result = SandboxResult(success=True, exit_code=0, stdout="test", output="test", execution_time=0.5)
        assert result.success is True
        assert result.stdout == "test"

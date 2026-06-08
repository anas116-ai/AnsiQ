"""Tests for LLM provider abstraction and ProviderFactory."""

from __future__ import annotations

import pytest

from ansiq.llm.base import (
    LLMConfig,
    LLMMessage,
    LLMProvider,
    LLMResponse,
    MessageRole,
    ProviderFactory,
    UsageInfo,
)


class TestProviderFactory:
    def test_register_and_create(self):
        """Test registering and creating a provider."""

        class TestProvider(LLMProvider):
            async def chat(self, messages):
                return LLMResponse(content="test", model="test")

            async def stream_chat(self, messages):
                yield "test"

            def get_model_list(self):
                return ["test"]

        ProviderFactory.register("test_provider", TestProvider)
        provider = ProviderFactory.create("test_provider", model="test-model")
        assert isinstance(provider, TestProvider)
        assert provider.config.model == "test-model"

    def test_list_providers(self):
        """Test listing registered providers."""
        providers = ProviderFactory.list_providers()
        assert isinstance(providers, list)

    def test_create_unknown_provider(self):
        """Test creating unknown provider raises ValueError."""
        with pytest.raises(ValueError, match="Unknown provider"):
            ProviderFactory.create("nonexistent", model="test")

    def test_double_register(self):
        """Test re-registering a provider overwrites."""

        class P1(LLMProvider):
            async def chat(self, messages):
                return LLMResponse(content="p1", model="m")
            async def stream_chat(self, messages):
                yield "p1"
            def get_model_list(self):
                return ["m"]

        class P2(LLMProvider):
            async def chat(self, messages):
                return LLMResponse(content="p2", model="m")
            async def stream_chat(self, messages):
                yield "p2"
            def get_model_list(self):
                return ["m"]

        ProviderFactory.register("dup", P1)
        ProviderFactory.register("dup", P2)
        provider = ProviderFactory.create("dup", model="m")
        assert isinstance(provider, P2)


class TestLLMConfig:
    def test_default_config(self):
        """Test LLMConfig default values."""
        config = LLMConfig(model="gpt-4o")
        assert config.temperature == 0.7
        assert config.max_tokens == 4096
        assert config.top_p == 1.0
        assert config.stop is None
        assert config.api_key is None
        assert config.base_url is None
        assert config.extra_kwargs == {}

    def test_custom_config(self):
        """Test LLMConfig with custom values."""
        config = LLMConfig(
            model="claude-3-sonnet",
            temperature=0.3,
            max_tokens=2048,
            top_p=0.9,
            stop=["\n\n"],
            api_key="sk-test",
            base_url="https://custom.api.com",
        )
        assert config.model == "claude-3-sonnet"
        assert config.temperature == 0.3
        assert config.max_tokens == 2048
        assert config.api_key == "sk-test"


class TestLLMResponse:
    def test_default_usage(self):
        """Test LLMResponse with default usage."""
        resp = LLMResponse(content="Hello", model="gpt-4o")
        assert resp.usage.prompt_tokens == 0
        assert resp.usage.total_tokens == 0

    def test_custom_usage(self):
        """Test LLMResponse with custom usage."""
        resp = LLMResponse(
            content="Hello",
            model="gpt-4o",
            usage=UsageInfo(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            finish_reason="stop",
        )
        assert resp.usage.total_tokens == 15
        assert resp.finish_reason == "stop"

    def test_tool_calls(self):
        """Test LLMResponse with tool calls."""
        resp = LLMResponse(
            content="",
            model="gpt-4o",
            tool_calls=[{"id": "call_1", "function": {"name": "test"}}],
        )
        assert resp.tool_calls is not None
        assert len(resp.tool_calls) == 1


class TestMessageRole:
    def test_role_values(self):
        """Test MessageRole enum values."""
        assert MessageRole.SYSTEM.value == "system"
        assert MessageRole.USER.value == "user"
        assert MessageRole.ASSISTANT.value == "assistant"
        assert MessageRole.TOOL.value == "tool"


class TestLLMMessage:
    def test_create_system(self):
        """Test creating system message with class method."""
        msg = LLMMessage.system("You are a helpful assistant.")
        assert msg.role == MessageRole.SYSTEM
        assert msg.content == "You are a helpful assistant."

    def test_create_user(self):
        """Test creating user message with class method."""
        msg = LLMMessage.user("Hello!")
        assert msg.role == MessageRole.USER
        assert msg.content == "Hello!"

    def test_create_assistant(self):
        """Test creating assistant message."""
        msg = LLMMessage.assistant("Hi there!")
        assert msg.role == MessageRole.ASSISTANT
        assert msg.content == "Hi there!"

    def test_create_assistant_with_tool_calls(self):
        """Test creating assistant message with tool calls."""
        tools = [{"id": "call_1", "type": "function", "function": {"name": "test"}}]
        msg = LLMMessage.assistant("", tool_calls=tools)
        assert msg.tool_calls == tools

    def test_create_tool(self):
        """Test creating tool result message."""
        msg = LLMMessage.tool("Result data", "call_123")
        assert msg.role == MessageRole.TOOL
        assert msg.content == "Result data"
        assert msg.tool_call_id == "call_123"

    def test_with_name(self):
        """Test message with name field."""
        msg = LLMMessage.user("data")
        msg.name = "function_response"
        assert msg.name == "function_response"

    def test_message_fields(self):
        """Test all optional fields."""
        msg = LLMMessage(
            role=MessageRole.ASSISTANT,
            content="Response",
            tool_calls=[],
            tool_call_id=None,
            name="test_func",
        )
        assert msg.tool_calls == []
        assert msg.name == "test_func"


class TestMockProviderIntegration:
    """Integration tests using the mock provider from conftest."""

    @pytest.mark.asyncio
    async def test_mock_chat(self, mock_provider):
        """Test mock provider chat returns expected response."""
        response = await mock_provider.chat([
            LLMMessage.system("Be helpful"),
            LLMMessage.user("Hi"),
        ])
        assert response.content == "Mock response"
        assert response.model == "mock-model"
        assert response.usage.prompt_tokens == 10

    @pytest.mark.asyncio
    async def test_mock_stream(self, mock_provider):
        """Test mock provider streaming."""
        chunks = []
        async for chunk in mock_provider.stream_chat([
            LLMMessage.user("Stream test"),
        ]):
            chunks.append(chunk)
        assert len(chunks) > 0
        assert "".join(chunks) == "Mock response"

    def test_mock_model_list(self, mock_provider):
        """Test mock provider model listing."""
        models = mock_provider.get_model_list()
        assert "mock-model-1" in models
        assert "mock-model-2" in models

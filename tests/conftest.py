"""Shared fixtures and mocks for all AnsiQ tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

import ansiq.llm.anthropic_provider  # noqa: F401
import ansiq.llm.huggingface_provider  # noqa: F401
import ansiq.llm.ollama_provider  # noqa: F401

# Import provider modules to trigger automatic registration
import ansiq.llm.openai_provider  # noqa: F401
from ansiq.core.agent import Agent, AgentIdentity
from ansiq.core.crew import Crew, ProcessType
from ansiq.core.task import Task
from ansiq.llm.base import (
    LLMConfig,
    LLMMessage,
    LLMProvider,
    LLMResponse,
    ProviderFactory,
    UsageInfo,
)

# ── Mock LLM Provider ──


class MockLLMProvider(LLMProvider):
    """Mock provider that returns predefined responses."""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.messages_received: list[list[LLMMessage]] = []
        self.response_content = "Mock response"
        self.model_list = ["mock-model-1", "mock-model-2"]

    async def chat(self, messages: list[LLMMessage]) -> LLMResponse:
        self.messages_received.append(messages)
        return LLMResponse(
            content=self.response_content,
            model=self.config.model,
            usage=UsageInfo(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            finish_reason="stop",
        )

    async def stream_chat(self, messages: list[LLMMessage]) -> AsyncIterator[str]:
        self.messages_received.append(messages)
        for chunk in ["Mock ", "response"]:
            yield chunk

    def get_model_list(self) -> list[str]:
        return self.model_list


@pytest.fixture
def mock_provider():
    """Create a mock LLM provider."""
    config = LLMConfig(model="mock-model", temperature=0)
    provider = MockLLMProvider(config)
    # Register for testing
    ProviderFactory._providers["mock"] = MockLLMProvider
    return provider


@pytest.fixture
def researcher_agent(mock_provider):
    """Create a researcher agent for testing."""
    return Agent(
        identity=AgentIdentity(
            role="Researcher",
            goal="Find and analyze information",
            backstory="An experienced researcher.",
        ),
        provider=mock_provider,
    )


@pytest.fixture
def writer_agent(mock_provider):
    """Create a writer agent for testing."""
    return Agent(
        identity=AgentIdentity(
            role="Writer",
            goal="Create clear written content",
            backstory="A professional writer.",
        ),
        provider=mock_provider,
    )


@pytest.fixture
def sample_task():
    """Create a sample task."""
    return Task(
        description="Research the topic {topic}",
        expected_output="A research summary",
    )


@pytest.fixture
def sample_crew(researcher_agent, writer_agent):
    """Create a sample crew with two agents."""
    research = Task(
        description="Research the topic {topic}",
        expected_output="Research results",
        agent=researcher_agent,
    )
    write = Task(
        description="Write about the research findings",
        expected_output="An article",
        agent=writer_agent,
        context=[research],
    )
    return Crew(
        agents=[researcher_agent, writer_agent],
        tasks=[research, write],
        process=ProcessType.PIPELINE,
    )


@pytest.fixture
def mock_factory():
    """Ensure mock provider is registered."""
    ProviderFactory._providers["mock"] = MockLLMProvider
    yield
    # Cleanup
    ProviderFactory._providers.pop("mock", None)


@pytest.fixture
def temp_db_path(tmp_path):
    """Get a temporary database path for memory tests."""
    return tmp_path / "test_memory.db"

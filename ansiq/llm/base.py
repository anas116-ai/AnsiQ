"""Abstract LLM provider interface — all providers implement this."""

from __future__ import annotations

import base64
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class MessageRole(StrEnum):
    """Standardized message roles across all providers."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ImageBlock(BaseModel):
    """An image attachment for multi-modal messages.

    Supports:
    - Raw image bytes (will be base64-encoded)
    - Base64-encoded image data
    - URL-based images
    - File paths (loaded automatically)
    """

    data: str  # base64-encoded image data OR URL
    format: str = "png"  # png, jpeg, webp, gif
    source: str = "base64"  # base64, url
    detail: str = "auto"  # auto, low, high

    @classmethod
    def from_path(cls, path: str, detail: str = "auto") -> ImageBlock:
        """Create an ImageBlock from a file path."""
        from pathlib import Path

        path_obj = Path(path)
        ext = path_obj.suffix.lower().lstrip(".")
        if ext == "jpg":
            ext = "jpeg"

        raw = path_obj.read_bytes()
        b64 = base64.b64encode(raw).decode("utf-8")
        return cls(data=b64, format=ext, source="base64", detail=detail)

    @classmethod
    def from_url(cls, url: str, detail: str = "auto") -> ImageBlock:
        """Create an ImageBlock from a URL."""
        if url.startswith("data:"):
            # Already a data URL — extract base64 part
            _, b64_part = url.split(",", 1)
            fmt = url.split(";")[0].split("/")[-1] if ";" in url else "png"
            return cls(data=b64_part, format=fmt, source="base64", detail=detail)
        return cls(data=url, format="url", source="url", detail=detail)

    @classmethod
    def from_bytes(cls, raw: bytes, fmt: str = "png", detail: str = "auto") -> ImageBlock:
        """Create an ImageBlock from raw bytes."""
        b64 = base64.b64encode(raw).decode("utf-8")
        return cls(data=b64, format=fmt, source="base64", detail=detail)


class LLMMessage(BaseModel):
    """Universal message format — translated to/from each provider's format.

    Supports both plain text and multi-modal content with images.
    """

    role: MessageRole
    content: str = ""
    images: list[ImageBlock] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    @classmethod
    def system(cls, content: str) -> LLMMessage:
        return cls(role=MessageRole.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str = "", images: list[ImageBlock] | None = None) -> LLMMessage:
        """Create a user message with optional images."""
        return cls(role=MessageRole.USER, content=content, images=images or [])

    @classmethod
    def assistant(cls, content: str = "", tool_calls: list[dict] | None = None) -> LLMMessage:
        return cls(role=MessageRole.ASSISTANT, content=content, tool_calls=tool_calls)

    @classmethod
    def tool(cls, content: str, tool_call_id: str) -> LLMMessage:
        return cls(role=MessageRole.TOOL, content=content, tool_call_id=tool_call_id)

    def has_images(self) -> bool:
        """Check if this message contains image attachments."""
        return len(self.images) > 0


class UsageInfo(BaseModel):
    """Token usage information."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMResponse(BaseModel):
    """Standardized response from any provider."""

    content: str
    model: str
    usage: UsageInfo = Field(default_factory=UsageInfo)
    finish_reason: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    raw: dict[str, Any] | None = None


class LLMConfig(BaseModel):
    """Universal configuration for any LLM provider."""

    model: str
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 1.0
    stop: list[str] | None = None
    api_key: str | None = None
    base_url: str | None = None
    organization: str | None = None
    extra_kwargs: dict[str, Any] = Field(default_factory=dict)


class LLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    def __init__(self, config: LLMConfig):
        self.config = config

    @abstractmethod
    async def chat(self, messages: list[LLMMessage]) -> LLMResponse:
        """Send a chat completion request."""
        ...

    @abstractmethod
    async def stream_chat(self, messages: list[LLMMessage]) -> AsyncIterator[str]:
        """Stream a chat completion response token by token."""
        ...
        if False:  # pragma: no cover
            yield ""

    @abstractmethod
    def get_model_list(self) -> list[str]:
        """Return list of available models from this provider."""
        ...


class ProviderFactory:
    """Creates LLM providers from configuration strings."""

    _providers: dict[str, type[LLMProvider]] = {}

    @classmethod
    def register(cls, name: str, provider_cls: type[LLMProvider]) -> None:
        """Register a provider class."""
        cls._providers[name] = provider_cls
        logger.debug("Registered LLM provider: %s", name)

    @classmethod
    def create(
        cls,
        provider_name: str,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        **kwargs: Any,
    ) -> LLMProvider:
        """Create a provider instance by name."""
        provider_cls = cls._providers.get(provider_name.lower())
        if not provider_cls:
            available = ", ".join(cls._providers.keys())
            raise ValueError(f"Unknown provider '{provider_name}'. Available: {available}")

        config = LLMConfig(
            model=model,
            api_key=api_key,
            base_url=base_url,
            **kwargs,
        )
        return provider_cls(config)

    @classmethod
    def list_providers(cls) -> list[str]:
        """List all registered provider names."""
        return list(cls._providers.keys())

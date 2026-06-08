"""Anthropic Claude provider — for Claude 3.5 Sonnet, Haiku, Opus models."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ansiq.llm.base import (
    LLMConfig,
    LLMMessage,
    LLMProvider,
    LLMResponse,
    MessageRole,
    ProviderFactory,
    UsageInfo,
)

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(LLMProvider):
    """Provider for Anthropic Claude models."""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.base_url = config.base_url or ANTHROPIC_API_URL
        self.api_key = config.api_key or ""
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "Content-Type": "application/json",
            }
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=httpx.Timeout(120.0),
            )
        return self._client

    def _convert_messages(self, messages: list[LLMMessage]) -> tuple[list[dict[str, Any]], str]:
        """Convert universal messages to Anthropic format.

        Handles image content for vision models (Claude 3 Sonnet, Opus, etc.).
        Returns (converted_messages, system_content).
        """
        converted = []
        system_content = ""

        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                system_content += msg.content + "\n"
                continue

            role = "user" if msg.role == MessageRole.USER else "assistant"

            if msg.has_images():
                # Multi-modal content: text + images
                content_blocks: list[dict[str, Any]] = []
                if msg.content:
                    content_blocks.append({"type": "text", "text": msg.content})
                for img in msg.images:
                    if img.source == "url":
                        # Anthropic doesn't support URL images; download and convert
                        content_blocks.append(
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": f"image/{img.format if img.format != 'url' else 'png'}",
                                    "data": img.data,
                                },
                            }
                        )
                    else:
                        content_blocks.append(
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": f"image/{img.format}",
                                    "data": img.data,
                                },
                            }
                        )
                entry: dict[str, Any] = {"role": role, "content": content_blocks}
            else:
                entry = {"role": role, "content": msg.content}

            converted.append(entry)

        return converted, system_content.strip()

    async def chat(self, messages: list[LLMMessage]) -> LLMResponse:
        """Send a chat completion to Anthropic."""
        client = await self._get_client()
        converted_messages, system = self._convert_messages(messages)

        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": converted_messages,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }
        if system:
            payload["system"] = system
        if self.config.stop:
            payload["stop_sequences"] = self.config.stop
        if self.config.extra_kwargs:
            payload.update(self.config.extra_kwargs)

        try:
            response = await client.post("/messages", json=payload)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            logger.error("Anthropic error: %s - %s", e.response.status_code, e.response.text)
            raise

        content_blocks = data.get("content", [])
        full_content = ""
        for block in content_blocks:
            if block.get("type") == "text":
                full_content += block.get("text", "")

        usage_data = data.get("usage", {})

        return LLMResponse(
            content=full_content,
            model=data.get("model", self.config.model),
            usage=UsageInfo(
                prompt_tokens=usage_data.get("input_tokens", 0),
                completion_tokens=usage_data.get("output_tokens", 0),
                total_tokens=(
                    usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0)
                ),
            ),
            finish_reason=data.get("stop_reason", "end_turn"),
            raw=data,
        )

    async def stream_chat(self, messages: list[LLMMessage]) -> AsyncIterator[str]:
        """Stream response from Anthropic."""
        client = await self._get_client()
        converted_messages, system = self._convert_messages(messages)

        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": converted_messages,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "stream": True,
        }
        if system:
            payload["system"] = system

        async with client.stream("POST", "/messages", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                if line.startswith("data: "):
                    chunk_data = line[6:]
                    try:
                        chunk = json.loads(chunk_data)
                        if chunk.get("type") == "content_block_delta":
                            delta = chunk.get("delta", {})
                            if delta.get("type") == "text_delta":
                                text = delta.get("text", "")
                                if text:
                                    yield text
                    except json.JSONDecodeError:
                        continue

    def get_model_list(self) -> list[str]:
        return [self.config.model]


# Register the provider
ProviderFactory.register("anthropic", AnthropicProvider)
ProviderFactory.register("claude", AnthropicProvider)

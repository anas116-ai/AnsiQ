"""OpenAI-compatible LLM provider.

Supports OpenAI API, OpenRouter, and any OpenAI-compatible endpoint.
Works with both API-key and local proxy setups.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ansiq.llm.base import (
    LLMConfig,
    LLMMessage,
    LLMProvider,
    LLMResponse,
    ProviderFactory,
    UsageInfo,
)

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """Provider for OpenAI-compatible APIs (OpenAI, OpenRouter, local proxies)."""

    DEFAULT_BASE_URL = "https://api.openai.com/v1"

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.base_url = (config.base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.api_key = config.api_key or ""
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            if self.config.organization:
                headers["OpenAI-Organization"] = self.config.organization

            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=httpx.Timeout(120.0),
            )
        return self._client

    def _convert_messages(self, messages: list[LLMMessage]) -> list[dict[str, Any]]:
        """Convert universal messages to OpenAI format.

        Handles image content for vision models (gpt-4o, gpt-4-turbo, etc.).
        """
        converted = []
        for msg in messages:
            entry: dict[str, Any] = {"role": msg.role.value}

            if msg.has_images():
                # Multi-modal content: text + images
                content_parts: list[dict[str, Any]] = []
                if msg.content:
                    content_parts.append({"type": "text", "text": msg.content})
                for img in msg.images:
                    if img.source == "url":
                        content_parts.append(
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": img.data,
                                    "detail": img.detail,
                                },
                            }
                        )
                    else:
                        content_parts.append(
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/{img.format};base64,{img.data}",
                                    "detail": img.detail,
                                },
                            }
                        )
                entry["content"] = content_parts
            else:
                entry["content"] = msg.content

            if msg.tool_calls:
                entry["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            if msg.name:
                entry["name"] = msg.name
            converted.append(entry)
        return converted

    async def chat(self, messages: list[LLMMessage]) -> LLMResponse:
        """Send a chat completion request."""
        client = await self._get_client()
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": self._convert_messages(messages),
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "top_p": self.config.top_p,
        }
        if self.config.stop:
            payload["stop"] = self.config.stop
        if self.config.extra_kwargs:
            payload.update(self.config.extra_kwargs)

        try:
            response = await client.post("/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            logger.error("OpenAI API error: %s - %s", e.response.status_code, e.response.text)
            raise
        except Exception as e:
            logger.error("OpenAI request failed: %s", e)
            raise

        choice = data["choices"][0]
        msg = choice.get("message", {})
        usage_data = data.get("usage", {})

        return LLMResponse(
            content=msg.get("content", "") or "",
            model=data.get("model", self.config.model),
            usage=UsageInfo(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
            ),
            finish_reason=choice.get("finish_reason"),
            tool_calls=msg.get("tool_calls"),
            raw=data,
        )

    async def stream_chat(self, messages: list[LLMMessage]) -> AsyncIterator[str]:
        """Stream a chat completion response."""
        client = await self._get_client()
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": self._convert_messages(messages),
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "top_p": self.config.top_p,
            "stream": True,
        }
        if self.config.stop:
            payload["stop"] = self.config.stop
        if self.config.extra_kwargs:
            payload.update(self.config.extra_kwargs)

        async with client.stream("POST", "/chat/completions", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                if line.startswith("data: "):
                    chunk_data = line[6:]
                    if chunk_data.strip() == "[DONE]":
                        break
                    try:
                        import json

                        chunk = json.loads(chunk_data)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue

    def get_model_list(self) -> list[str]:
        """Return known models for this provider."""
        return [self.config.model]


# Register the provider
ProviderFactory.register("openai", OpenAIProvider)
ProviderFactory.register("openrouter", OpenAIProvider)

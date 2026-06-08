"""Ollama LLM provider — run local models on your machine.

No API key needed. Works with any model pulled via `ollama pull`.
"""

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
    ProviderFactory,
    UsageInfo,
)

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    """Provider for local Ollama models — zero API key needed."""

    DEFAULT_BASE_URL = "http://localhost:11434"

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.base_url = (config.base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(300.0),  # Local models can be slow
            )
        return self._client

    def _convert_messages(self, messages: list[LLMMessage]) -> list[dict[str, Any]]:
        """Convert universal messages to Ollama format.

        Handles image content for vision models (llava, bakllava, etc.).
        """
        converted = []
        for msg in messages:
            entry: dict[str, Any] = {"role": msg.role.value}

            if msg.has_images():
                # Ollama supports images via a separate 'images' field
                content_parts = []
                if msg.content:
                    content_parts.append(msg.content)
                img_data_list = []
                for img in msg.images:
                    if img.source == "url":
                        # For URL-based images, add as text reference
                        content_parts.append(f"[Image: {img.data}]")
                    else:
                        img_data_list.append(img.data)
                entry["content"] = "\n".join(content_parts) if content_parts else " "
                if img_data_list:
                    entry["images"] = img_data_list
            else:
                entry["content"] = msg.content

            if msg.tool_calls:
                entry["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            converted.append(entry)
        return converted

    async def chat(self, messages: list[LLMMessage]) -> LLMResponse:
        """Send a chat completion request to local Ollama."""
        client = await self._get_client()
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": self._convert_messages(messages),
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
                "top_p": self.config.top_p,
            },
            "stream": False,
        }
        if self.config.stop:
            payload["options"]["stop"] = self.config.stop
        if self.config.extra_kwargs:
            payload["options"].update(self.config.extra_kwargs)

        try:
            response = await client.post("/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise RuntimeError(
                    f"Model '{self.config.model}' not found. Run: ollama pull {self.config.model}"
                ) from e
            logger.error("Ollama error: %s - %s", e.response.status_code, e.response.text)
            raise
        except httpx.ConnectError as e:
            raise RuntimeError(
                "Cannot connect to Ollama. Make sure it's running: ollama serve"
            ) from e

        return LLMResponse(
            content=data.get("message", {}).get("content", ""),
            model=data.get("model", self.config.model),
            usage=UsageInfo(
                prompt_tokens=data.get("prompt_eval_count", 0),
                completion_tokens=data.get("eval_count", 0),
                total_tokens=(data.get("prompt_eval_count", 0) + data.get("eval_count", 0)),
            ),
            finish_reason=data.get("done_reason", "stop"),
            tool_calls=data.get("message", {}).get("tool_calls"),
            raw=data,
        )

    async def stream_chat(self, messages: list[LLMMessage]) -> AsyncIterator[str]:
        """Stream a chat completion from local Ollama."""
        client = await self._get_client()
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": self._convert_messages(messages),
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
                "top_p": self.config.top_p,
            },
            "stream": True,
        }
        if self.config.stop:
            payload["options"]["stop"] = self.config.stop

        async with client.stream("POST", "/api/chat", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        yield content
                    if chunk.get("done", False):
                        break
                except json.JSONDecodeError:
                    continue

    async def list_local_models(self) -> list[dict[str, Any]]:
        """List models available in local Ollama instance."""
        client = await self._get_client()
        try:
            response = await client.get("/api/tags")
            response.raise_for_status()
            data = response.json()
            return data.get("models", [])
        except Exception as e:
            logger.warning("Could not list Ollama models: %s", e)
            return []

    def get_model_list(self) -> list[str]:
        """Return configured model for this provider."""
        return [self.config.model]


# Register the provider
ProviderFactory.register("ollama", OllamaProvider)

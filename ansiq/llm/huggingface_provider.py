"""HuggingFace Inference API provider — open-source models via HF.

Can use free Inference API (no key needed for some models) or paid Inference Endpoints.
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
    MessageRole,
    ProviderFactory,
)

logger = logging.getLogger(__name__)


class HuggingFaceProvider(LLMProvider):
    """Provider for HuggingFace Inference API / Inference Endpoints."""

    DEFAULT_BASE_URL = "https://api-inference.huggingface.co"

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.base_url = (config.base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Content-Type": "application/json"}
            if self.config.api_key:
                headers["Authorization"] = f"Bearer {self.config.api_key}"

            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=httpx.Timeout(120.0),
            )
        return self._client

    def _build_prompt(self, messages: list[LLMMessage]) -> str:
        """Build a prompt string from messages for HF chat models."""
        parts = []
        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                parts.append(f"<|system|>\n{msg.content}</s>")
            elif msg.role == MessageRole.USER:
                parts.append(f"<|user|>\n{msg.content}</s>")
            elif msg.role == MessageRole.ASSISTANT:
                parts.append(f"<|assistant|>\n{msg.content}</s>")
            elif msg.role == MessageRole.TOOL:
                parts.append(f"<|tool|>\n{msg.content}</s>")
        parts.append("<|assistant|>\n")
        return "\n".join(parts)

    async def chat(self, messages: list[LLMMessage]) -> LLMResponse:
        """Send a chat completion request to HuggingFace."""
        client = await self._get_client()
        prompt = self._build_prompt(messages)

        payload: dict[str, Any] = {
            "inputs": prompt,
            "parameters": {
                "temperature": self.config.temperature,
                "max_new_tokens": self.config.max_tokens,
                "top_p": self.config.top_p,
            },
        }
        if self.config.stop:
            payload["parameters"]["stop"] = self.config.stop

        model_path = self.config.model
        if "/" not in model_path:
            model_path = f"meta-llama/{model_path}"

        try:
            response = await client.post(
                f"/models/{model_path}/v1/chat/completions",
                json={
                    "model": model_path,
                    "messages": [{"role": m.role.value, "content": m.content} for m in messages],
                    "temperature": self.config.temperature,
                    "max_tokens": self.config.max_tokens,
                    "top_p": self.config.top_p,
                },
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError:
            # Fallback to text generation endpoint
            try:
                resp = await client.post(f"/models/{model_path}", json=payload)
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list):
                    text = data[0].get("generated_text", "")
                    # Remove prompt from generated text
                    if text.startswith(prompt):
                        text = text[len(prompt) :]
                    return LLMResponse(
                        content=text.strip(),
                        model=self.config.model,
                    )
                return LLMResponse(
                    content=str(data),
                    model=self.config.model,
                )
            except Exception as e:
                logger.error("HuggingFace request failed: %s", e)
                raise

        choice = data.get("choices", [{}])[0]
        msg_content = choice.get("message", {}).get("content", "")

        return LLMResponse(
            content=msg_content or "",
            model=data.get("model", self.config.model),
            finish_reason=choice.get("finish_reason"),
            raw=data,
        )

    async def stream_chat(self, messages: list[LLMMessage]) -> AsyncIterator[str]:
        """Stream response from HuggingFace."""
        client = await self._get_client()
        model_path = self.config.model
        if "/" not in model_path:
            model_path = f"meta-llama/{model_path}"

        payload: dict[str, Any] = {
            "model": model_path,
            "messages": [{"role": m.role.value, "content": m.content} for m in messages],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "top_p": self.config.top_p,
            "stream": True,
        }

        async with client.stream(
            "POST", f"/models/{model_path}/v1/chat/completions", json=payload
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                if line.startswith("data: "):
                    chunk_data = line[6:]
                    if chunk_data.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(chunk_data)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue

    def get_model_list(self) -> list[str]:
        return [self.config.model]


# Register the provider
ProviderFactory.register("huggingface", HuggingFaceProvider)
ProviderFactory.register("hf", HuggingFaceProvider)

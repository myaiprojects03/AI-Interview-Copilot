"""Groq LLM provider (free tier). Groq exposes an OpenAI-compatible API."""

import json
from collections.abc import AsyncIterator

import httpx

from app.providers.base import ChatMessage, LLMProvider, ProviderError


class GroqLLM(LLMProvider):
    name = "groq"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout: float = 30.0,
        reasoning_effort: str | None = None,
    ):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._reasoning_effort = reasoning_effort

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int = 600,
        temperature: float = 0.4,
    ) -> AsyncIterator[str]:
        payload = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if self._reasoning_effort:
            payload["reasoning_effort"] = self._reasoning_effort
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream(
                    "POST", f"{self._base_url}/chat/completions", json=payload, headers=headers
                ) as response:
                    if response.status_code != 200:
                        body = (await response.aread()).decode(errors="replace")[:300]
                        raise ProviderError(
                            f"Groq LLM returned HTTP {response.status_code}: {body}"
                        )
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[len("data:"):].strip()
                        if data == "[DONE]":
                            break
                        chunk = json.loads(data)
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {}).get("content")
                        if delta:
                            yield delta
        except httpx.HTTPError as exc:
            raise ProviderError(f"Could not reach Groq LLM: {exc.__class__.__name__}") from exc

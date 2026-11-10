"""Groq LLM provider (free tier). Groq exposes an OpenAI-compatible API."""

import asyncio
import json
from collections.abc import AsyncIterator

import httpx

from app.providers import retry
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
        # Retry once if the request fails before any text arrives (rate limit, 5xx, network).
        # Once tokens are streaming, a failure is reported instead: replaying would repeat text.
        started = False
        for attempt in range(retry.ATTEMPTS):
            last = attempt == retry.ATTEMPTS - 1
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    async with client.stream(
                        "POST", f"{self._base_url}/chat/completions", json=payload, headers=headers
                    ) as response:
                        if response.status_code != 200:
                            body = (await response.aread()).decode(errors="replace")
                            if response.status_code in retry.RETRYABLE_STATUS and not last:
                                await asyncio.sleep(retry.wait_seconds(response))
                                continue
                            raise ProviderError(
                                retry.error_message("The AI (Groq)", response.status_code, body)
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
                                started = True
                                yield delta
                        return
            except httpx.HTTPError as exc:
                if started or last:
                    raise ProviderError(
                        f"Could not reach the AI (Groq): {exc.__class__.__name__}"
                    ) from exc
                await asyncio.sleep(retry.DEFAULT_WAIT_S)

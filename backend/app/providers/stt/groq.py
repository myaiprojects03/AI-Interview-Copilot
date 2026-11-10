"""Groq Whisper speech-to-text (free tier). Used on VAD-cut speech segments, not a raw stream."""

import asyncio

import httpx

from app.providers import retry
from app.providers.base import ProviderError, STTProvider, Transcript


class GroqWhisperSTT(STTProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str, base_url: str, timeout: float = 30.0):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def transcribe(
        self, audio: bytes, *, filename: str = "audio.wav", language: str | None = "en"
    ) -> Transcript:
        data = {"model": self._model, "response_format": "verbose_json", "temperature": "0"}
        if language:
            data["language"] = language
        response = None
        for attempt in range(retry.ATTEMPTS):
            last = attempt == retry.ATTEMPTS - 1
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(
                        f"{self._base_url}/audio/transcriptions",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        data=data,
                        files={"file": (filename, audio)},
                    )
            except httpx.HTTPError as exc:
                if last:
                    raise ProviderError(
                        f"Could not reach Groq STT: {exc.__class__.__name__}"
                    ) from exc
                await asyncio.sleep(retry.DEFAULT_WAIT_S)
                continue
            if response.status_code in retry.RETRYABLE_STATUS and not last:
                await asyncio.sleep(retry.wait_seconds(response))
                continue
            break
        if response.status_code != 200:
            raise ProviderError(
                retry.error_message("Speech-to-text (Groq)", response.status_code, response.text)
            )
        body = response.json()
        return Transcript(
            text=(body.get("text") or "").strip(),
            language=body.get("language"),
            duration_seconds=body.get("duration"),
        )

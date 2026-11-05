"""Groq Whisper speech-to-text (free tier). Used on VAD-cut speech segments, not a raw stream."""

import httpx

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
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    data=data,
                    files={"file": (filename, audio)},
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Could not reach Groq STT: {exc.__class__.__name__}") from exc
        if response.status_code != 200:
            raise ProviderError(
                f"Groq STT returned HTTP {response.status_code}: {response.text[:300]}"
            )
        body = response.json()
        return Transcript(
            text=(body.get("text") or "").strip(),
            language=body.get("language"),
            duration_seconds=body.get("duration"),
        )

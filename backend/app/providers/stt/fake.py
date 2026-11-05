"""Key-free STT used in tests and offline development."""

from app.providers.base import STTProvider, Transcript


class FakeSTT(STTProvider):
    name = "fake"

    def __init__(self, text: str = "Tell me about yourself."):
        self._text = text

    async def transcribe(
        self, audio: bytes, *, filename: str = "audio.wav", language: str | None = "en"
    ) -> Transcript:
        return Transcript(text=self._text, language=language, duration_seconds=None)

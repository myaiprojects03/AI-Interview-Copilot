"""Key-free LLM used in tests and offline development."""

from collections.abc import AsyncIterator

from app.providers.base import ChatMessage, LLMProvider


class FakeLLM(LLMProvider):
    name = "fake"

    def __init__(self, reply: str = "This is a fake suggestion from the test provider."):
        self._reply = reply

    async def stream_chat(
        self, messages: list[ChatMessage], *, max_tokens: int = 600, temperature: float = 0.4
    ) -> AsyncIterator[str]:
        for word in self._reply.split(" "):
            yield word + " "

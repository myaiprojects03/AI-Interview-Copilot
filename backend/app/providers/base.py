"""Provider interfaces. Every external AI service sits behind one of these, so a provider
can be swapped (Groq -> OpenAI, Groq Whisper -> Deepgram, pgvector -> Pinecone) by config.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal


class ProviderError(RuntimeError):
    """Raised when a provider call fails. The message is safe to show to the user."""


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int = 600,
        temperature: float = 0.4,
    ) -> AsyncIterator[str]:
        """Yield the reply token by token (text deltas)."""

    async def complete(self, messages: list[ChatMessage], **kwargs) -> str:
        return "".join([part async for part in self.stream_chat(messages, **kwargs)])


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str | None = None
    duration_seconds: float | None = None


class STTProvider(ABC):
    name: str

    @abstractmethod
    async def transcribe(
        self, audio: bytes, *, filename: str = "audio.wav", language: str | None = "en"
    ) -> Transcript:
        """Transcribe one audio segment (a VAD-cut chunk of speech)."""


class EmbeddingProvider(ABC):
    """Unit-length vectors, so a dot product is the cosine similarity.

    Passages (CV/JD chunks) and queries (interview questions) are embedded separately
    because retrieval models like bge add an instruction to queries.
    The vector store lives in app/documents/store.py (Postgres + pgvector, or in-memory).
    """

    name: str
    dimensions: int

    @abstractmethod
    async def embed_passages(self, texts: list[str]) -> list[list[float]]: ...

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]: ...

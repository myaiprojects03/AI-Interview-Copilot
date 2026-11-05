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
    name: str
    dimensions: int

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text."""


@dataclass(frozen=True)
class RetrievedChunk:
    text: str
    score: float
    metadata: dict


class VectorStore(ABC):
    name: str

    @abstractmethod
    async def upsert(
        self, user_id: str, items: list[tuple[str, list[float], dict]]
    ) -> None:
        """Store (text, vector, metadata) items. Always scoped to one user."""

    @abstractmethod
    async def search(
        self, user_id: str, vector: list[float], *, top_k: int = 5
    ) -> list[RetrievedChunk]:
        """Return the closest chunks for this user only."""

    @abstractmethod
    async def delete_user(self, user_id: str) -> None:
        """Remove all of a user's data (privacy requirement)."""

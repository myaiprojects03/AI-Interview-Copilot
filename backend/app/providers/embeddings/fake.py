"""Deterministic bag-of-words embeddings for tests: texts sharing words score higher."""

import hashlib
import math
import re

from app.providers.base import EmbeddingProvider

_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "with", "you", "your",
         "i", "me", "my", "how", "what", "would", "do", "did", "is", "are", "tell", "about"}


class FakeEmbeddings(EmbeddingProvider):
    name = "fake"
    dimensions = 384

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dimensions
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            if word in _STOP:
                continue
            word = word.rstrip("s") or word
            h = int(hashlib.md5(word.encode()).hexdigest(), 16)
            v[h % self.dimensions] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    async def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vec(text)

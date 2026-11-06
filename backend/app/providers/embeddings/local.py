"""Local embeddings with fastembed (ONNX, CPU). Free, no API key, ~5 ms per question.

The model (~67 MB) downloads on first use and is cached; call `warm_up()` at startup so
the first interview question isn't slow.
"""

import asyncio
import threading

from app.providers.base import EmbeddingProvider


class LocalEmbeddings(EmbeddingProvider):
    name = "fastembed"

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5", dimensions: int = 384):
        self.model_name = model
        self.dimensions = dimensions
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(self.model_name)
        return self._model

    async def warm_up(self) -> None:
        await asyncio.to_thread(self._load)

    async def embed_passages(self, texts: list[str]) -> list[list[float]]:
        def run() -> list[list[float]]:
            return [v.tolist() for v in self._load().passage_embed(texts)]

        return await asyncio.to_thread(run) if texts else []

    async def embed_query(self, text: str) -> list[float]:
        def run() -> list[float]:
            return next(iter(self._load().query_embed([text]))).tolist()

        return await asyncio.to_thread(run)

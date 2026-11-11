"""Local embeddings (ONNX on CPU). Free, no API key, ~5 ms per question.

The model is BAAI/bge-small-en-v1.5 in the quantised ONNX export that fastembed uses
(Qdrant/bge-small-en-v1.5-onnx-Q), run directly with onnxruntime and a plain-Python
WordPiece tokenizer. It gives the same vectors as fastembed without its dependencies, which
keeps the Vercel bundle under its size limit.

The model files (~67 MB) live in one plain folder:
- on Vercel, scripts/fetch_model.py downloads them at build time into backend/models and
  they are loaded from there (the file system is read-only at run time);
- locally, without that folder, they download on first use into ~/.cache/interview-copilot.
Call `warm_up()` at startup so the first question isn't slow.
"""

import asyncio
import logging
import os
import tempfile
import threading
from pathlib import Path

from app.providers.base import EmbeddingProvider
from app.providers.embeddings.wordpiece import WordPieceTokenizer

# model name -> (Hugging Face repo, pinned revision, ONNX file, dimensions)
MODELS = {
    "BAAI/bge-small-en-v1.5": (
        "Qdrant/bge-small-en-v1.5-onnx-Q",
        "aa8f8b060edb00e03bfdd08813a2949946c8ba55",
        "model_optimized.onnx",
        384,
    ),
}
TOKENIZER_FILES = ("tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
                   "config.json")
MAX_TOKENS = 512
BATCH_SIZE = 32
# Vercel's file system is read-only except /tmp.
DEFAULT_CACHE = (
    Path(tempfile.gettempdir()) / "interview-copilot-models"
    if os.environ.get("VERCEL")
    else Path.home() / ".cache" / "interview-copilot"
)
log = logging.getLogger(__name__)


def model_folder(model: str, root: Path) -> Path:
    return root / model.split("/")[-1]


def download_model(model: str, root: Path) -> Path:
    """Download the model files into root/<model> (skips files already there)."""
    import httpx

    repo, revision, onnx_file, _ = MODELS[model]
    folder = model_folder(model, root)
    folder.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        for name in (onnx_file, *TOKENIZER_FILES):
            path = folder / name
            if path.exists() and path.stat().st_size > 0:
                continue
            url = f"https://huggingface.co/{repo}/resolve/{revision}/{name}"
            tmp = path.with_suffix(path.suffix + ".part")
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with open(tmp, "wb") as fh:
                    for chunk in response.iter_bytes(1 << 20):
                        fh.write(chunk)
            tmp.replace(path)
    return folder


class _Model:
    def __init__(self, folder: Path, onnx_file: str):
        import onnxruntime as ort

        self.tokenizer = WordPieceTokenizer.from_file(folder / "tokenizer.json", MAX_TOKENS)

        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            str(folder / onnx_file), options, providers=["CPUExecutionProvider"]
        )
        self.inputs = {i.name for i in self.session.get_inputs()}

    def embed(self, texts: list[str]) -> list[list[float]]:
        import numpy as np

        out: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            encoded = [self.tokenizer.encode(t) for t in texts[start:start + BATCH_SIZE]]
            width = max(len(e) for e in encoded)
            pad = self.tokenizer.pad
            ids = np.array([e + [pad] * (width - len(e)) for e in encoded], dtype=np.int64)
            mask = np.array([[1] * len(e) + [0] * (width - len(e)) for e in encoded],
                            dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = self.session.run(None, feed)[0]
            cls = hidden[:, 0].astype(np.float32)  # CLS pooling, as bge expects
            norms = np.linalg.norm(cls, axis=1, keepdims=True)
            out.extend((cls / np.maximum(norms, 1e-12)).tolist())
        return out


class LocalEmbeddings(EmbeddingProvider):
    name = "local-onnx"

    def __init__(
        self,
        model: str = "BAAI/bge-small-en-v1.5",
        dimensions: int = 384,
        cache_dir: Path | None = None,
    ):
        if model not in MODELS:
            raise ValueError(f"Unsupported embedding model {model!r}; known: {list(MODELS)}")
        self.model_name = model
        self.dimensions = MODELS[model][3]
        # A bundled model folder: load from it (download elsewhere only if it's missing).
        self._bundled = cache_dir is not None
        self._root = Path(cache_dir) if cache_dir else DEFAULT_CACHE
        self._model: _Model | None = None
        self._lock = threading.Lock()

    def _load(self) -> _Model:
        with self._lock:
            if self._model is None:
                folder = model_folder(self.model_name, self._root)
                onnx_file = MODELS[self.model_name][2]
                if not (folder / onnx_file).exists():
                    if self._bundled:
                        # Should not happen on Vercel (the build bundles it), but rather than
                        # fail, fetch it once per instance into a writable folder.
                        log.warning("embedding model missing in %s; downloading", folder)
                    folder = download_model(self.model_name, DEFAULT_CACHE)
                self._model = _Model(folder, onnx_file)
        return self._model

    async def warm_up(self) -> None:
        await asyncio.to_thread(self._load)

    async def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(lambda: self._load().embed(texts)) if texts else []

    async def embed_query(self, text: str) -> list[float]:
        return (await asyncio.to_thread(lambda: self._load().embed([text])))[0]

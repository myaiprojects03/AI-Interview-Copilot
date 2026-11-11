"""The plain-Python tokenizer must match the model's own tokenizer token for token, or the
vectors (and every stored CV) would drift."""

import json
from pathlib import Path

import pytest

from app.core.config import BACKEND_DIR
from app.providers.embeddings.wordpiece import WordPieceTokenizer

TOKENIZER = BACKEND_DIR / "models" / "bge-small-en-v1.5" / "tokenizer.json"
pytestmark = pytest.mark.skipif(not TOKENIZER.exists(),
                                reason="run scripts/fetch_model.py first")

SAMPLES = [
    "Tell me about a time you disagreed with your manager?",
    "Senior Engineer, Brightlane (2019–2023): led payments; cut p95 latency by 40%.",
    "Kubernetes/Terraform, AWS (EKS, S3), PostgreSQL & Redis — C++, C#, Node.js, .NET",
    "Café résumé naïve Ångström Straße İstanbul ﬁnance",
    "中文简历 日本語 한국어 Ελληνικά русский العربية",
    "emoji 🚀 ok 👍🏽, tabs\tand\nnewlines\r\n nbsp​zero line",
    "email: someone@example.com, url https://x.io/a?b=1#c, $1,200.50, 3.5x, ~/path_to\\file",
    "Literal [CLS] and [MASK] tokens, ### hashes, ##sub",
    "x" * 150 + " supercalifragilisticexpialidocious antidisestablishmentarianism",
    "",
    "word " * 700,
]


def _corpus() -> list[str]:
    texts = list(SAMPLES)
    for path in (BACKEND_DIR / "evals").rglob("*"):
        if path.suffix in (".md", ".txt"):
            texts.append(path.read_text(encoding="utf-8"))
        elif path.suffix == ".json":
            texts.extend(s for s in _strings(json.loads(path.read_text(encoding="utf-8"))))
    return texts


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def test_matches_the_reference_tokenizer():
    tokenizers = pytest.importorskip("tokenizers")
    reference = tokenizers.Tokenizer.from_file(str(TOKENIZER))
    reference.enable_truncation(max_length=512)
    ours = WordPieceTokenizer.from_file(Path(TOKENIZER))
    texts = _corpus()
    assert len(texts) > len(SAMPLES)
    for text in texts:
        assert ours.encode(text) == reference.encode(text).ids, text[:80]

"""BERT WordPiece tokenizer in plain Python, for the bge embedding model.

It reproduces the model's tokenizer.json (BertNormalizer with lowercase + accent stripping,
BertPreTokenizer, WordPiece with "##", [CLS] ... [SEP], truncation to 512) so the
`tokenizers` package and the Hugging Face download libraries it pulls in (~30 MB) don't
have to ship in the Vercel bundle. tests/test_wordpiece.py checks it token for token
against `tokenizers`.
"""

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

SPECIAL = ("[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]")
_SPECIAL_RE = re.compile("(" + "|".join(re.escape(s) for s in SPECIAL) + ")")


def _is_whitespace(ch: str) -> bool:
    return ch in " \t\n\r" or ch.isspace() or unicodedata.category(ch) == "Zs"


def _is_control(ch: str) -> bool:
    if ch in "\t\n\r":
        return False
    return unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn")


def _is_punctuation(ch: str) -> bool:
    cp = ord(ch)
    if 33 <= cp <= 47 or 58 <= cp <= 64 or 91 <= cp <= 96 or 123 <= cp <= 126:
        return True
    return unicodedata.category(ch).startswith("P")


def _is_chinese(cp: int) -> bool:
    return (
        0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or 0x20000 <= cp <= 0x2A6DF
        or 0x2A700 <= cp <= 0x2B73F or 0x2B740 <= cp <= 0x2B81F or 0x2B820 <= cp <= 0x2CEAF
        or 0xF900 <= cp <= 0xFAFF or 0x2F800 <= cp <= 0x2FA1F
    )


def _normalize(text: str) -> str:
    out = []
    for ch in text:
        if ch in ("\0", "�") or _is_control(ch):
            continue
        if _is_whitespace(ch):
            out.append(" ")
        elif _is_chinese(ord(ch)):
            out.append(f" {ch} ")
        else:
            out.append(ch)
    text = unicodedata.normalize("NFD", "".join(out))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.lower()


def _pre_tokenize(text: str) -> list[str]:
    words: list[str] = []
    current: list[str] = []
    for ch in text:
        if _is_whitespace(ch):
            if current:
                words.append("".join(current))
                current = []
        elif _is_punctuation(ch):
            if current:
                words.append("".join(current))
                current = []
            words.append(ch)
        else:
            current.append(ch)
    if current:
        words.append("".join(current))
    return words


class WordPieceTokenizer:
    def __init__(self, vocab: dict[str, int], max_tokens: int = 512,
                 max_word_chars: int = 100):
        self.vocab = vocab
        self.max_tokens = max_tokens
        self.max_word_chars = max_word_chars
        self.unk = vocab["[UNK]"]
        self.cls = vocab["[CLS]"]
        self.sep = vocab["[SEP]"]
        self.pad = vocab["[PAD]"]
        self._word = lru_cache(maxsize=50_000)(self._word_uncached)

    @classmethod
    def from_file(cls, path: Path, max_tokens: int = 512) -> "WordPieceTokenizer":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        model = data["model"]
        return cls(model["vocab"], max_tokens, model.get("max_input_chars_per_word", 100))

    def _word_uncached(self, word: str) -> tuple[int, ...]:
        if len(word) > self.max_word_chars:
            return (self.unk,)
        ids = []
        start = 0
        while start < len(word):
            end = len(word)
            found = None
            while start < end:
                piece = word[start:end] if start == 0 else "##" + word[start:end]
                found = self.vocab.get(piece)
                if found is not None:
                    break
                end -= 1
            if found is None:
                return (self.unk,)
            ids.append(found)
            start = end
        return tuple(ids)

    def encode(self, text: str) -> list[int]:
        """Token ids with [CLS] and [SEP], truncated to max_tokens."""
        ids: list[int] = []
        for part in _SPECIAL_RE.split(text):
            if part in SPECIAL:
                ids.append(self.vocab[part])
                continue
            for word in _pre_tokenize(_normalize(part)):
                ids.extend(self._word(word))
        return [self.cls, *ids[: self.max_tokens - 2], self.sep]

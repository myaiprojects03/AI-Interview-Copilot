"""Turn an uploaded CV or job description into a stored, searchable document."""

import asyncio
import logging
import re

from app.documents.chunking import chunk_text
from app.documents.store import DocKind, DocumentStore, NewChunk, StoredDocument
from app.providers.base import ChatMessage, EmbeddingProvider, LLMProvider, ProviderError

log = logging.getLogger(__name__)

MAX_CHARS = 40_000  # ~10 pages; more than any CV or JD needs

_SUMMARY_PROMPTS = {
    "cv": """Write a compact profile of this candidate for an interview assistant.
Include: name, current title and total years of experience; then each role as \
"Title, Company (dates): one key achievement" keeping the CV's exact numbers; top skills; \
education. Plain text, at most 130 words. Use only facts stated in the CV.""",
    "jd": """Summarise this job description for a candidate preparing to interview.
Include: company name and what it does, role title and seniority, the 5 most important \
requirements, and any values or priorities it stresses. Plain text, at most 110 words. \
Use only facts stated in the text.""",
}


def _fallback_summary(text: str, words: int = 120) -> str:
    return " ".join(text.split()[:words])


def default_title(kind: DocKind, text: str, filename: str | None) -> str:
    if filename:
        return re.sub(r"\.(pdf|docx|txt|md)$", "", filename, flags=re.IGNORECASE)[:80]
    first = next((line.strip("#*- ") for line in text.splitlines() if line.strip()), "")
    label = "CV" if kind == "cv" else "Job description"
    return f"{label}: {first[:60]}" if first else label


async def summarize(llm: LLMProvider, kind: DocKind, text: str) -> str:
    messages = [
        ChatMessage("system", _SUMMARY_PROMPTS[kind]),
        ChatMessage("user", text[:12_000]),
    ]
    try:
        summary = (await llm.complete(messages, max_tokens=700, temperature=0.2)).strip()
    except ProviderError as exc:
        log.warning("summary failed, using the first words instead: %s", exc)
        return _fallback_summary(text)
    return summary or _fallback_summary(text)


async def ingest(
    *,
    user_id: str,
    kind: DocKind,
    text: str,
    filename: str | None,
    title: str | None,
    store: DocumentStore,
    embedder: EmbeddingProvider,
    llm: LLMProvider,
) -> StoredDocument:
    text = text[:MAX_CHARS]
    chunks = chunk_text(text)
    embeddings, summary = await asyncio.gather(
        embedder.embed_passages([c.text for c in chunks]),
        summarize(llm, kind, text),
    )
    return await store.add(
        user_id,
        kind=kind,
        title=(title or "").strip()[:120] or default_title(kind, text, filename),
        filename=filename,
        content=text,
        summary=summary,
        chunks=[
            NewChunk(c.text, e, {"section": c.section, "role": c.role})
            for c, e in zip(chunks, embeddings, strict=True)
        ],
    )

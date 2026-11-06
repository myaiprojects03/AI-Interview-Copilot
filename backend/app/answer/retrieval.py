"""Pick the CV and job-description chunks most relevant to a question.

The selected documents are loaded once per session (a CV is a few dozen chunks), so each
question costs one local query embedding (~5 ms) and a dot product per chunk, with no
database round trip during the interview.
"""

from dataclasses import dataclass, field

from app.answer.gaps import SkillGap
from app.documents.chunking import chunk_text
from app.documents.store import DocumentStore, StoredChunk, StoredDocument
from app.providers.base import EmbeddingProvider


@dataclass(frozen=True)
class ScoredChunk:
    chunk: StoredChunk
    score: float

    @property
    def label(self) -> str:
        meta = self.chunk.metadata or {}
        return meta.get("role") or meta.get("section") or self.chunk.content.split("\n")[0][:60]


@dataclass
class InterviewContext:
    cv: StoredDocument | None = None
    jd: StoredDocument | None = None
    chunks: list[StoredChunk] = field(default_factory=list)
    sample_cv_text: str | None = None  # used when the user hasn't uploaded a CV
    gaps: list[SkillGap] = field(default_factory=list)  # job skills the CV doesn't show

    @property
    def cv_summary(self) -> str:
        if self.cv:
            return self.cv.summary
        return self.sample_cv_text or ""

    @property
    def fact_text(self) -> str:
        """Everything the answer may quote figures from."""
        parts = [self.cv.content if self.cv else (self.sample_cv_text or "")]
        if self.jd:
            parts.append(self.jd.content)
        return "\n".join(parts)

    def public(self) -> dict:
        return {
            "cv": {"id": self.cv.id, "title": self.cv.title} if self.cv else None,
            "jd": {"id": self.jd.id, "title": self.jd.title} if self.jd else None,
            "using_sample_cv": self.cv is None,
            "gaps": [g.skill for g in self.gaps],
        }


async def load_context(
    store: DocumentStore,
    user_id: str,
    *,
    cv_id: str | None,
    jd_id: str | None,
    sample_cv_text: str,
) -> InterviewContext:
    """cv_id / jd_id: a document id, "latest", or None for none."""

    async def pick(kind: str, ref: str | None) -> StoredDocument | None:
        if not ref:
            return None
        if ref == "latest":
            return await store.latest(user_id, kind)  # type: ignore[arg-type]
        doc = await store.get(user_id, ref)
        return doc if doc and doc.kind == kind else None

    cv = await pick("cv", cv_id)
    jd = await pick("jd", jd_id)
    ids = [d.id for d in (cv, jd) if d]
    chunks = await store.chunks(user_id, ids) if ids else []
    return InterviewContext(
        cv=cv, jd=jd, chunks=chunks, sample_cv_text=None if cv else sample_cv_text
    )


async def retrieve(
    context: InterviewContext,
    embedder: EmbeddingProvider,
    question: str,
    *,
    k_cv: int = 4,
    k_jd: int = 2,
) -> list[ScoredChunk]:
    if not context.chunks:
        return []
    q = await embedder.embed_query(question)
    scored = [
        ScoredChunk(c, sum(a * b for a, b in zip(q, c.embedding, strict=False)))
        for c in context.chunks
    ]
    scored.sort(key=lambda s: s.score, reverse=True)
    cv = [s for s in scored if s.chunk.kind == "cv"][:k_cv]
    jd = [s for s in scored if s.chunk.kind == "jd"][:k_jd]
    return cv + jd


def sample_chunks(text: str) -> list[str]:
    return [c.text for c in chunk_text(text)]

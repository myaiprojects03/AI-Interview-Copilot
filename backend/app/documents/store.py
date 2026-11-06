"""Where CVs, job descriptions and their embedded chunks are kept.

Every method takes a user_id and only ever touches that user's rows.

- PostgresStore: Supabase Postgres + pgvector (production; survives restarts, shared by all
  backend instances, so the API stays stateless).
- MemoryStore: in-process dict (tests, or local dev before DATABASE_URL is set).
"""

import asyncio
import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

DocKind = Literal["cv", "jd"]

SCHEMA_SQL = (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")


@dataclass(frozen=True)
class StoredDocument:
    id: str
    user_id: str
    kind: DocKind
    title: str
    filename: str | None
    content: str
    summary: str
    chunk_count: int
    created_at: datetime


@dataclass(frozen=True)
class StoredChunk:
    document_id: str
    kind: DocKind
    position: int
    content: str
    embedding: list[float]
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class NewChunk:
    content: str
    embedding: list[float]
    metadata: dict


class DocumentStore(ABC):
    name: str

    @abstractmethod
    async def add(
        self,
        user_id: str,
        *,
        kind: DocKind,
        title: str,
        filename: str | None,
        content: str,
        summary: str,
        chunks: list[NewChunk],
    ) -> StoredDocument: ...

    @abstractmethod
    async def list_documents(
        self, user_id: str, kind: DocKind | None = None
    ) -> list[StoredDocument]:
        """Newest first."""

    @abstractmethod
    async def get(self, user_id: str, doc_id: str) -> StoredDocument | None: ...

    @abstractmethod
    async def chunks(self, user_id: str, doc_ids: list[str]) -> list[StoredChunk]: ...

    @abstractmethod
    async def delete(self, user_id: str, doc_id: str) -> bool: ...

    async def latest(self, user_id: str, kind: DocKind) -> StoredDocument | None:
        docs = await self.list_documents(user_id, kind)
        return docs[0] if docs else None

    async def close(self) -> None:
        return None


def _valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (ValueError, TypeError):
        return False
    return True


class MemoryStore(DocumentStore):
    name = "memory"

    def __init__(self) -> None:
        self._docs: dict[str, StoredDocument] = {}
        self._chunks: dict[str, list[StoredChunk]] = {}
        self._lock = asyncio.Lock()

    async def add(self, user_id, *, kind, title, filename, content, summary, chunks):
        doc = StoredDocument(
            id=str(uuid.uuid4()),
            user_id=user_id,
            kind=kind,
            title=title,
            filename=filename,
            content=content,
            summary=summary,
            chunk_count=len(chunks),
            created_at=datetime.now(UTC),
        )
        async with self._lock:
            self._docs[doc.id] = doc
            self._chunks[doc.id] = [
                StoredChunk(doc.id, kind, i, c.content, c.embedding, c.metadata)
                for i, c in enumerate(chunks)
            ]
        return doc

    async def list_documents(self, user_id, kind=None):
        docs = [
            d
            for d in self._docs.values()
            if d.user_id == user_id and (kind is None or d.kind == kind)
        ]
        return sorted(docs, key=lambda d: d.created_at, reverse=True)

    async def get(self, user_id, doc_id):
        doc = self._docs.get(doc_id)
        return doc if doc and doc.user_id == user_id else None

    async def chunks(self, user_id, doc_ids):
        out: list[StoredChunk] = []
        for doc_id in doc_ids:
            if await self.get(user_id, doc_id):
                out.extend(self._chunks.get(doc_id, []))
        return out

    async def delete(self, user_id, doc_id):
        async with self._lock:
            doc = self._docs.get(doc_id)
            if not doc or doc.user_id != user_id:
                return False
            del self._docs[doc_id]
            self._chunks.pop(doc_id, None)
            return True


class PostgresStore(DocumentStore):
    name = "postgres"

    def __init__(self, pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> "PostgresStore":
        import asyncpg
        from pgvector.asyncpg import register_vector

        # Create the extension and tables before the pool registers the vector type.
        conn = await asyncpg.connect(dsn, statement_cache_size=0)
        try:
            await conn.execute(SCHEMA_SQL)
        finally:
            await conn.close()
        pool = await asyncpg.create_pool(
            dsn, min_size=1, max_size=5, statement_cache_size=0, init=register_vector
        )
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    @staticmethod
    def _doc(row) -> StoredDocument:
        return StoredDocument(
            id=str(row["id"]),
            user_id=row["user_id"],
            kind=row["kind"],
            title=row["title"],
            filename=row["filename"],
            content=row["content"],
            summary=row["summary"],
            chunk_count=row["chunk_count"],
            created_at=row["created_at"],
        )

    _SELECT = """
        select d.*, (select count(*) from document_chunks c where c.document_id = d.id)
               as chunk_count
        from documents d
    """

    async def add(self, user_id, *, kind, title, filename, content, summary, chunks):
        import numpy as np

        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """insert into documents (user_id, kind, title, filename, content, summary)
                   values ($1, $2, $3, $4, $5, $6) returning id""",
                user_id, kind, title, filename, content, summary,
            )
            await conn.executemany(
                """insert into document_chunks
                   (document_id, user_id, position, content, metadata, embedding)
                   values ($1, $2, $3, $4, $5::jsonb, $6)""",
                [
                    (row["id"], user_id, i, c.content, json.dumps(c.metadata),
                     np.asarray(c.embedding, dtype=np.float32))
                    for i, c in enumerate(chunks)
                ],
            )
            doc = await conn.fetchrow(self._SELECT + " where d.id = $1", row["id"])
        return self._doc(doc)

    async def list_documents(self, user_id, kind=None):
        async with self._pool.acquire() as conn:
            if kind:
                rows = await conn.fetch(
                    self._SELECT + " where d.user_id = $1 and d.kind = $2"
                    " order by d.created_at desc",
                    user_id, kind,
                )
            else:
                rows = await conn.fetch(
                    self._SELECT + " where d.user_id = $1 order by d.created_at desc", user_id
                )
        return [self._doc(r) for r in rows]

    async def get(self, user_id, doc_id):
        if not _valid_uuid(doc_id):
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                self._SELECT + " where d.user_id = $1 and d.id = $2", user_id, uuid.UUID(doc_id)
            )
        return self._doc(row) if row else None

    async def chunks(self, user_id, doc_ids):
        ids = [uuid.UUID(d) for d in doc_ids if _valid_uuid(d)]
        if not ids:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """select c.document_id, d.kind, c.position, c.content, c.metadata, c.embedding
                   from document_chunks c join documents d on d.id = c.document_id
                   where c.user_id = $1 and c.document_id = any($2::uuid[])
                   order by c.document_id, c.position""",
                user_id, ids,
            )
        return [
            StoredChunk(
                document_id=str(r["document_id"]),
                kind=r["kind"],
                position=r["position"],
                content=r["content"],
                embedding=[float(x) for x in r["embedding"]],
                metadata=json.loads(r["metadata"]) if isinstance(r["metadata"], str)
                else dict(r["metadata"]),
            )
            for r in rows
        ]

    async def delete(self, user_id, doc_id):
        if not _valid_uuid(doc_id):
            return False
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "delete from documents where user_id = $1 and id = $2", user_id, uuid.UUID(doc_id)
            )
        return result.endswith(" 1")

"""Runs against a real Postgres + pgvector (e.g. Supabase) only when TEST_DATABASE_URL is set:

    TEST_DATABASE_URL=postgresql://... pytest tests/test_postgres_store.py

Each run uses a unique user_id and deletes what it created.
"""

import os
import uuid

import pytest

from app.documents.store import NewChunk, PostgresStore

DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL not set")


def vec(i: int) -> list[float]:
    v = [0.0] * 384
    v[i] = 1.0
    return v


async def test_round_trip_and_user_scoping():
    store = await PostgresStore.connect(DSN)
    me, other = f"test-{uuid.uuid4()}", f"test-{uuid.uuid4()}"
    try:
        doc = await store.add(
            me, kind="cv", title="Test CV", filename="cv.pdf", content="hello world",
            summary="A summary",
            chunks=[
                NewChunk("first", vec(0), {"role": "Engineer"}),
                NewChunk("second", vec(1), {}),
            ],
        )
        assert doc.chunk_count == 2

        assert [d.id for d in await store.list_documents(me, "cv")] == [doc.id]
        assert await store.list_documents(other) == []
        assert await store.get(other, doc.id) is None
        assert await store.chunks(other, [doc.id]) == []

        chunks = await store.chunks(me, [doc.id])
        assert [c.content for c in chunks] == ["first", "second"]
        assert chunks[0].metadata == {"role": "Engineer"}
        assert chunks[0].embedding[0] == pytest.approx(1.0)

        assert await store.delete(other, doc.id) is False
        assert await store.delete(me, doc.id) is True
        assert await store.chunks(me, [doc.id]) == []  # cascade
        assert await store.get(me, "not-a-uuid") is None
    finally:
        for d in await store.list_documents(me):
            await store.delete(me, d.id)
        await store.close()


async def test_many_instances_starting_together_do_not_deadlock():
    """Serverless hosts start several instances at once; each sets up the tables."""
    import asyncio

    import asyncpg

    from app.documents.store import ensure_schema

    async def start():
        conn = await asyncpg.connect(DSN, statement_cache_size=0)
        try:
            return await ensure_schema(conn)
        finally:
            await conn.close()

    results = await asyncio.gather(*(start() for _ in range(6)))
    assert sum(results) <= 1  # the script runs at most once, then is skipped
    assert await start() is False

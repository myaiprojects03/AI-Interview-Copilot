"""Account store against a real Postgres (Supabase). Runs only when TEST_DATABASE_URL is set.
Uses throwaway user ids and deletes what it creates."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.accounts.store import PostgresAccountStore, Subscription
from app.documents.store import PostgresStore

DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL not set")


async def test_subscription_usage_and_history_round_trip():
    docs = await PostgresStore.connect(DSN)
    store = PostgresAccountStore(docs.pool)
    me, other = f"test-{uuid.uuid4()}", f"test-{uuid.uuid4()}"
    month = "2099-01"
    try:
        assert await store.get_subscription(me) is None
        await store.upsert_subscription(Subscription(
            user_id=me, plan="starter", status="active", provider="fake",
            customer_id=f"cus-{me}", subscription_id="sub-1",
            current_period_end=datetime(2099, 2, 1, tzinfo=UTC),
        ))
        await store.upsert_subscription(Subscription(
            user_id=me, plan="pro", status="active", provider="fake",
            customer_id=f"cus-{me}", subscription_id="sub-1", cancel_at_period_end=True,
        ))
        sub = await store.get_subscription(me)
        assert (sub.plan, sub.cancel_at_period_end) == ("pro", True)
        assert await store.user_for_customer(f"cus-{me}") == me

        assert await store.add_usage(me, month, 10.5) == pytest.approx(10.5)
        assert await store.add_usage(me, month, 4.5) == pytest.approx(15.0)
        assert await store.usage_seconds(other, month) == 0.0

        sid = await store.create_session(me, cv_title="CV", jd_title=None)
        await store.add_turn(me, sid, "interviewer", "Why us?")
        await store.add_turn(other, sid, "interviewer", "not mine")  # ignored: wrong owner
        started = datetime.now(UTC) - timedelta(minutes=5)  # tolerate clock skew
        await store.add_answer(me, sid, question="Why us?", question_type="general",
                               answer="Because…", status="done",
                               timings={"stt_ms": 210, "llm_first_token_ms": 480})
        mine = [t for t in await store.answer_timings(started) if t.timings.get("stt_ms") == 210]
        assert mine and mine[0].timings["llm_first_token_ms"] == 480
        await store.finish_session(me, sid, 42.0)

        listed = await store.list_sessions(me)
        assert [(s.id, s.question_count, s.audio_seconds) for s in listed] == [(sid, 1, 42.0)]
        assert await store.list_sessions(other) == []
        session, turns, answers = await store.get_session(me, sid)
        assert [t.text for t in turns] == ["Why us?"]
        assert answers[0].answer == "Because…"
        assert await store.get_session(other, sid) is None
        assert await store.get_session(me, "not-a-uuid") is None

        assert await store.delete_session(other, sid) is False
        assert await store.delete_history(me) == 1
        assert await store.list_sessions(me) == []
    finally:
        async with docs.pool.acquire() as conn:
            for table in ("interview_sessions", "usage_monthly", "subscriptions"):
                await conn.execute(f"delete from {table} where user_id = any($1)", [me, other])
        await docs.close()

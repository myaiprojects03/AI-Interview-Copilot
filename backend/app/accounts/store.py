"""Per-user account data: subscription, monthly usage and interview history.

Every method takes a user_id and only touches that user's rows.
MemoryAccountStore for tests / local dev; PostgresAccountStore shares the documents pool.
"""

import asyncio
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from app.db import retry_on_disconnect


def now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Subscription:
    user_id: str
    plan: str = "free"  # "free" | "starter" | "pro"
    status: str = "none"  # none | active | trialing | past_due | paused | canceled
    provider: str | None = None  # "paddle" | "fake"
    customer_id: str | None = None
    subscription_id: str | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    updated_at: datetime = field(default_factory=now)


@dataclass(frozen=True)
class InterviewSession:
    id: str
    user_id: str
    started_at: datetime
    ended_at: datetime | None
    audio_seconds: float
    cv_title: str | None
    jd_title: str | None
    question_count: int = 0


@dataclass(frozen=True)
class Turn:
    speaker: str
    text: str
    created_at: datetime


@dataclass(frozen=True)
class Answer:
    question: str
    question_type: str | None
    answer: str
    status: str
    created_at: datetime


class AccountStore(ABC):
    @abstractmethod
    async def get_subscription(self, user_id: str) -> Subscription | None: ...

    @abstractmethod
    async def upsert_subscription(self, sub: Subscription) -> None: ...

    @abstractmethod
    async def user_for_customer(self, customer_id: str) -> str | None: ...

    @abstractmethod
    async def add_usage(self, user_id: str, month: str, seconds: float) -> float:
        """Add seconds to the month's total and return the new total."""

    @abstractmethod
    async def usage_seconds(self, user_id: str, month: str) -> float: ...

    @abstractmethod
    async def create_session(
        self, user_id: str, *, cv_title: str | None, jd_title: str | None
    ) -> str: ...

    @abstractmethod
    async def add_turn(self, user_id: str, session_id: str, speaker: str, text: str) -> None: ...

    @abstractmethod
    async def add_answer(
        self, user_id: str, session_id: str, *, question: str, question_type: str | None,
        answer: str, status: str,
    ) -> None: ...

    @abstractmethod
    async def finish_session(self, user_id: str, session_id: str, audio_seconds: float) -> None: ...

    @abstractmethod
    async def list_sessions(self, user_id: str, limit: int = 50) -> list[InterviewSession]: ...

    @abstractmethod
    async def get_session(
        self, user_id: str, session_id: str
    ) -> tuple[InterviewSession, list[Turn], list[Answer]] | None: ...

    @abstractmethod
    async def delete_session(self, user_id: str, session_id: str) -> bool: ...

    @abstractmethod
    async def delete_history(self, user_id: str) -> int:
        """Delete every interview session (with transcripts). Returns how many."""


def _valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (ValueError, TypeError):
        return False
    return True


class MemoryAccountStore(AccountStore):
    def __init__(self) -> None:
        self._subs: dict[str, Subscription] = {}
        self._usage: dict[tuple[str, str], float] = {}
        self._sessions: dict[str, InterviewSession] = {}
        self._turns: dict[str, list[Turn]] = {}
        self._answers: dict[str, list[Answer]] = {}
        self._lock = asyncio.Lock()

    async def get_subscription(self, user_id):
        return self._subs.get(user_id)

    async def upsert_subscription(self, sub):
        self._subs[sub.user_id] = replace(sub, updated_at=now())

    async def user_for_customer(self, customer_id):
        return next((s.user_id for s in self._subs.values() if s.customer_id == customer_id), None)

    async def add_usage(self, user_id, month, seconds):
        async with self._lock:
            total = self._usage.get((user_id, month), 0.0) + seconds
            self._usage[(user_id, month)] = total
            return total

    async def usage_seconds(self, user_id, month):
        return self._usage.get((user_id, month), 0.0)

    def _owned(self, user_id: str, session_id: str) -> InterviewSession | None:
        s = self._sessions.get(session_id)
        return s if s and s.user_id == user_id else None

    async def create_session(self, user_id, *, cv_title, jd_title):
        sid = str(uuid.uuid4())
        self._sessions[sid] = InterviewSession(sid, user_id, now(), None, 0.0, cv_title, jd_title)
        self._turns[sid], self._answers[sid] = [], []
        return sid

    async def add_turn(self, user_id, session_id, speaker, text):
        if self._owned(user_id, session_id):
            self._turns[session_id].append(Turn(speaker, text, now()))

    async def add_answer(self, user_id, session_id, *, question, question_type, answer, status):
        if self._owned(user_id, session_id):
            self._answers[session_id].append(Answer(question, question_type, answer, status, now()))

    async def finish_session(self, user_id, session_id, audio_seconds):
        s = self._owned(user_id, session_id)
        if s:
            self._sessions[session_id] = replace(s, ended_at=now(), audio_seconds=audio_seconds)

    async def list_sessions(self, user_id, limit=50):
        rows = [
            replace(s, question_count=len(self._answers.get(s.id, [])))
            for s in self._sessions.values()
            if s.user_id == user_id
        ]
        return sorted(rows, key=lambda s: s.started_at, reverse=True)[:limit]

    async def get_session(self, user_id, session_id):
        s = self._owned(user_id, session_id)
        if not s:
            return None
        answers = list(self._answers[session_id])
        return replace(s, question_count=len(answers)), list(self._turns[session_id]), answers

    async def delete_session(self, user_id, session_id):
        if not self._owned(user_id, session_id):
            return False
        for d in (self._sessions, self._turns, self._answers):
            d.pop(session_id, None)
        return True

    async def delete_history(self, user_id):
        ids = [s.id for s in self._sessions.values() if s.user_id == user_id]
        for sid in ids:
            await self.delete_session(user_id, sid)
        return len(ids)


@retry_on_disconnect
class PostgresAccountStore(AccountStore):
    def __init__(self, pool) -> None:
        self._pool = pool

    async def get_subscription(self, user_id):
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("select * from subscriptions where user_id = $1", user_id)
        return Subscription(**dict(row)) if row else None

    async def upsert_subscription(self, sub):
        async with self._pool.acquire() as conn:
            await conn.execute(
                """insert into subscriptions (user_id, plan, status, provider, customer_id,
                       subscription_id, current_period_end, cancel_at_period_end, updated_at)
                   values ($1, $2, $3, $4, $5, $6, $7, $8, now())
                   on conflict (user_id) do update set plan = excluded.plan,
                       status = excluded.status, provider = excluded.provider,
                       customer_id = excluded.customer_id,
                       subscription_id = excluded.subscription_id,
                       current_period_end = excluded.current_period_end,
                       cancel_at_period_end = excluded.cancel_at_period_end, updated_at = now()""",
                sub.user_id, sub.plan, sub.status, sub.provider, sub.customer_id,
                sub.subscription_id, sub.current_period_end, sub.cancel_at_period_end,
            )

    async def user_for_customer(self, customer_id):
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                "select user_id from subscriptions where customer_id = $1 limit 1", customer_id
            )

    async def add_usage(self, user_id, month, seconds):
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                """insert into usage_monthly (user_id, month, seconds) values ($1, $2, $3)
                   on conflict (user_id, month)
                   do update set seconds = usage_monthly.seconds + excluded.seconds
                   returning seconds""",
                user_id, month, seconds,
            )

    async def usage_seconds(self, user_id, month):
        async with self._pool.acquire() as conn:
            value = await conn.fetchval(
                "select seconds from usage_monthly where user_id = $1 and month = $2",
                user_id, month,
            )
        return float(value or 0.0)

    async def create_session(self, user_id, *, cv_title, jd_title):
        async with self._pool.acquire() as conn:
            sid = await conn.fetchval(
                """insert into interview_sessions (user_id, cv_title, jd_title)
                   values ($1, $2, $3) returning id""",
                user_id, cv_title, jd_title,
            )
        return str(sid)

    async def add_turn(self, user_id, session_id, speaker, text):
        async with self._pool.acquire() as conn:
            await conn.execute(
                """insert into session_turns (session_id, user_id, speaker, text)
                   select id, user_id, $3, $4 from interview_sessions
                   where id = $1 and user_id = $2""",
                uuid.UUID(session_id), user_id, speaker, text,
            )

    async def add_answer(self, user_id, session_id, *, question, question_type, answer, status):
        async with self._pool.acquire() as conn:
            await conn.execute(
                """insert into session_answers
                       (session_id, user_id, question, question_type, answer, status)
                   select id, user_id, $3, $4, $5, $6 from interview_sessions
                   where id = $1 and user_id = $2""",
                uuid.UUID(session_id), user_id, question, question_type, answer, status,
            )

    async def finish_session(self, user_id, session_id, audio_seconds):
        async with self._pool.acquire() as conn:
            await conn.execute(
                """update interview_sessions set ended_at = now(), audio_seconds = $3
                   where id = $1 and user_id = $2""",
                uuid.UUID(session_id), user_id, audio_seconds,
            )

    _LIST = """select s.*, (select count(*) from session_answers a where a.session_id = s.id)
                   as question_count
               from interview_sessions s"""

    @staticmethod
    def _session(row) -> InterviewSession:
        d = dict(row)
        d["id"] = str(d["id"])
        return InterviewSession(**d)

    async def list_sessions(self, user_id, limit=50):
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                self._LIST + " where s.user_id = $1 order by s.started_at desc limit $2",
                user_id, limit,
            )
        return [self._session(r) for r in rows]

    async def get_session(self, user_id, session_id):
        if not _valid_uuid(session_id):
            return None
        sid = uuid.UUID(session_id)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                self._LIST + " where s.user_id = $1 and s.id = $2", user_id, sid
            )
            if not row:
                return None
            turns = await conn.fetch(
                "select speaker, text, created_at from session_turns where session_id = $1 "
                "order by id", sid,
            )
            answers = await conn.fetch(
                "select question, question_type, answer, status, created_at from session_answers "
                "where session_id = $1 order by id", sid,
            )
        return (
            self._session(row),
            [Turn(**dict(t)) for t in turns],
            [Answer(**dict(a)) for a in answers],
        )

    async def delete_session(self, user_id, session_id):
        if not _valid_uuid(session_id):
            return False
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "delete from interview_sessions where user_id = $1 and id = $2",
                user_id, uuid.UUID(session_id),
            )
        return result.endswith(" 1")

    async def delete_history(self, user_id):
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "delete from interview_sessions where user_id = $1", user_id
            )
        return int(result.split()[-1])

"""WebSocket for a live copilot session.

Client -> server
  first:  {"type": "auth", "token": "<Supabase access token>"} (when sign-in is enabled)
  binary: 1 byte channel (0 = interviewer / tab audio, 1 = candidate / mic)
          + 16 kHz mono PCM16 little-endian audio
  text:   {"type": "start", "session_type": "mixed" | "behavioral" | "technical",
           "cv_id": id | "latest" | null, "jd_id": id | "latest" | null,
           "history_id": id to continue after a reconnect (optional)}
          {"type": "set_session_type", "session_type": ...}
          {"type": "pause"} | {"type": "answer_now"} | {"type": "regenerate"}
          {"type": "stop_answer"}

Server -> client (JSON)
  ready, usage, context, history, speech, transcript, transcript_discard, suggestion_start,
  suggestion_delta, suggestion_end, limit_reached, error. See app/realtime/session.py.
  Close codes: 4401 not signed in, 4402 monthly minutes used up (don't reconnect).
"""

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.accounts.store import AccountStore
from app.answer.gaps import find_gaps
from app.answer.prompts import SAMPLE_CV
from app.answer.retrieval import load_context
from app.billing.plans import PLANS, month_key
from app.billing.service import quota
from app.core.auth import AuthError, User
from app.core.deps import EmbedderDep, SettingsDep, StoreDep, VerifierDep, authenticate
from app.providers.base import LLMProvider, ProviderError
from app.providers.registry import get_llm, get_stt
from app.realtime.session import INTERVIEWER, CopilotSession

log = logging.getLogger(__name__)
router = APIRouter()

MAX_AUDIO_FRAME_BYTES = 64 * 1024


GAP_TIMEOUT_S = 8.0


async def _apply_documents(
    session: CopilotSession, msg: dict, store, user_id: str, llm: LLMProvider
) -> None:
    """On "start": load the chosen CV / job description ("latest" by default), then list the
    job's skills the CV doesn't show so answers don't claim them."""

    def ref(key: str) -> str | None:
        value = msg.get(key, "latest")
        return value if isinstance(value, str) and value else None

    context = await load_context(
        store, user_id, cv_id=ref("cv_id"), jd_id=ref("jd_id"), sample_cv_text=SAMPLE_CV
    )
    if context.jd:
        try:
            context.gaps = await asyncio.wait_for(
                find_gaps(
                    llm,
                    cv_text=context.cv.content if context.cv else SAMPLE_CV,
                    jd_text=context.jd.content,
                    cache_key=(context.cv.id if context.cv else "sample", context.jd.id),
                ),
                timeout=GAP_TIMEOUT_S,
            )
        except TimeoutError:
            log.warning("gap analysis timed out; continuing without it")
    session.context = context


AUTH_TIMEOUT_S = 10.0
METER_FLUSH_S = 15.0  # write usage to the database every 15 s of live audio
BYTES_PER_SECOND = 16000 * 2  # 16 kHz, 16-bit mono
CLOSE_AUTH = 4401
CLOSE_LIMIT = 4402


def _limit_message(plan: str) -> str:
    name = PLANS[plan].name
    return (
        f"You've used all your {PLANS[plan].minutes} interview minutes on the {name} plan this "
        "month. Upgrade to keep going."
    )


async def _who(ws: WebSocket, settings, verifier) -> User:
    """Browsers can't set headers on a WebSocket, so the token is the first message:
    {"type": "auth", "token": "..."}"""
    if not settings.auth_enabled:
        return await authenticate(None, settings, verifier)
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), AUTH_TIMEOUT_S))
    except (TimeoutError, json.JSONDecodeError, KeyError, WebSocketDisconnect) as exc:
        raise AuthError("Sign in to continue.") from exc
    if not isinstance(first, dict) or first.get("type") != "auth":
        raise AuthError("Sign in to continue.")
    return await authenticate(first.get("token"), settings, verifier)


RESUME_WINDOW = timedelta(minutes=30)


async def _history_for(accounts: AccountStore, user_id: str, session, msg: dict) -> str:
    """After a reconnect the browser sends the interview it was on ("history_id") so the
    transcript continues in one place. Only the owner's recent interviews can be resumed."""
    resume = msg.get("history_id")
    if isinstance(resume, str) and resume:
        found = await accounts.get_session(user_id, resume)
        if found and datetime.now(UTC) - found[0].started_at < RESUME_WINDOW:
            return resume
    ctx = session.context
    return await accounts.create_session(
        user_id,
        cv_title=ctx.cv.title if ctx.cv else "Sample CV",
        jd_title=ctx.jd.title if ctx.jd else None,
    )


@router.websocket("/ws/session")
async def session_socket(
    ws: WebSocket,
    settings: SettingsDep,
    store: StoreDep,
    embedder: EmbedderDep,
    verifier: VerifierDep,
) -> None:
    accounts: AccountStore = ws.app.state.accounts
    await ws.accept()
    try:
        user = await _who(ws, settings, verifier)
    except AuthError as exc:
        await ws.send_json({"type": "error", "code": "auth", "message": str(exc),
                            "retryable": False})
        await ws.close(code=CLOSE_AUTH)
        return

    usage = await quota(accounts, user.id)
    if usage["remaining_seconds"] <= 0:
        await ws.send_json({"type": "limit_reached", "plan": usage["plan"],
                            "message": _limit_message(usage["plan"])})
        await ws.close(code=CLOSE_LIMIT)
        return

    try:
        stt = get_stt(settings)
        llm = get_llm(settings)
    except ProviderError as exc:
        await ws.send_json({"type": "error", "message": str(exc), "retryable": False})
        await ws.close(code=1011)
        return

    # ---- interview history: written in the background so audio is never blocked ----
    history_id: str | None = None
    writes: asyncio.Queue[dict] = asyncio.Queue()

    async def write(item: dict) -> None:
        try:
            if item["kind"] == "turn":
                await accounts.add_turn(user.id, history_id, item["speaker"], item["text"])
            else:
                await accounts.add_answer(
                    user.id, history_id, question=item["question"],
                    question_type=item["question_type"], answer=item["answer"],
                    status=item["status"], timings=item.get("timings"),
                )
        except Exception:  # noqa: BLE001 - history must never break the live session
            log.exception("saving interview history failed")

    async def writer() -> None:
        while True:
            await write(await writes.get())

    def record(item: dict) -> None:
        if history_id:
            writes.put_nowait(item)

    # ---- usage metering: live interviewer audio counts, paused time doesn't ----
    limit = usage["limit_seconds"]
    used_at_start = usage["used_seconds"]
    metered = 0.0
    unflushed = 0.0

    async def flush() -> float:
        nonlocal unflushed
        seconds, unflushed = unflushed, 0.0
        used = await accounts.add_usage(user.id, month_key(), seconds) if seconds else (
            used_at_start + metered
        )
        outbound.put_nowait({"type": "usage", "plan": usage["plan"], "limit_seconds": limit,
                             "remaining_seconds": max(0.0, limit - used)})
        return used

    outbound: asyncio.Queue[dict] = asyncio.Queue()
    session = CopilotSession(
        stt=stt, llm=llm, settings=settings, emit=outbound.put_nowait, embedder=embedder,
        record=record,
    )

    async def sender() -> None:
        while True:
            await ws.send_json(await outbound.get())

    send_task = asyncio.create_task(sender())
    write_task = asyncio.create_task(writer())
    await session.start()
    outbound.put_nowait({"type": "ready"})
    outbound.put_nowait({"type": "usage", "plan": usage["plan"], "limit_seconds": limit,
                         "remaining_seconds": usage["remaining_seconds"]})
    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            data = message.get("bytes")
            if data is not None:
                if not 1 < len(data) <= MAX_AUDIO_FRAME_BYTES:
                    continue
                session.on_audio(data[0], data[1:])
                if data[0] == INTERVIEWER:
                    seconds = (len(data) - 1) / BYTES_PER_SECOND
                    metered += seconds
                    unflushed += seconds
                    over = used_at_start + metered >= limit
                    if unflushed >= METER_FLUSH_S or over:
                        if await flush() >= limit:
                            outbound.put_nowait({"type": "limit_reached", "plan": usage["plan"],
                                                 "message": _limit_message(usage["plan"])})
                            await asyncio.sleep(0.2)  # let the sender deliver it
                            await ws.close(code=CLOSE_LIMIT)
                            break
                continue
            text = message.get("text")
            if text:
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if msg.get("type") == "start":
                    try:
                        await _apply_documents(session, msg, store, user.id, llm)
                    except Exception:  # noqa: BLE001 - keep the session alive on the sample CV
                        log.exception("loading documents failed")
                        outbound.put_nowait(
                            {"type": "error", "message": "Couldn't load your CV; using the sample."}
                        )
                    outbound.put_nowait({"type": "context", **session.context.public()})
                    if history_id is None:
                        history_id = await _history_for(accounts, user.id, session, msg)
                        outbound.put_nowait({"type": "history", "id": history_id})
                session.on_control(msg)
    except WebSocketDisconnect:
        pass
    finally:
        await session.close()
        with contextlib.suppress(Exception):
            if unflushed:
                await accounts.add_usage(user.id, month_key(), unflushed)
            if history_id:
                write_task.cancel()
                while not writes.empty():
                    await write(writes.get_nowait())
                await accounts.finish_session(user.id, history_id, metered)
        for task in (send_task, write_task):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

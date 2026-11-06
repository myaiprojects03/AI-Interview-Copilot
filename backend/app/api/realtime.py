"""WebSocket for a live copilot session.

Client -> server
  binary: 1 byte channel (0 = interviewer / tab audio, 1 = candidate / mic)
          + 16 kHz mono PCM16 little-endian audio
  text:   {"type": "start", "session_type": "mixed" | "behavioral" | "technical",
           "cv_id": id | "latest" | null, "jd_id": id | "latest" | null}
          {"type": "set_session_type", "session_type": ...}
          {"type": "pause"} | {"type": "answer_now"} | {"type": "regenerate"}
          {"type": "stop_answer"}

Server -> client (JSON)
  ready, speech, transcript, transcript_discard, suggestion_start, suggestion_delta,
  suggestion_end, error. See app/realtime/session.py.
"""

import asyncio
import contextlib
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.answer.gaps import find_gaps
from app.answer.prompts import SAMPLE_CV
from app.answer.retrieval import load_context
from app.core.deps import EmbedderDep, SettingsDep, StoreDep, UserDep
from app.providers.base import LLMProvider, ProviderError
from app.providers.registry import get_llm, get_stt
from app.realtime.session import CopilotSession

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


@router.websocket("/ws/session")
async def session_socket(
    ws: WebSocket, settings: SettingsDep, store: StoreDep, embedder: EmbedderDep, user_id: UserDep
) -> None:
    await ws.accept()
    try:
        stt = get_stt(settings)
        llm = get_llm(settings)
    except ProviderError as exc:
        await ws.send_json({"type": "error", "message": str(exc), "retryable": False})
        await ws.close(code=1011)
        return

    outbound: asyncio.Queue[dict] = asyncio.Queue()
    session = CopilotSession(
        stt=stt, llm=llm, settings=settings, emit=outbound.put_nowait, embedder=embedder
    )

    async def sender() -> None:
        while True:
            await ws.send_json(await outbound.get())

    send_task = asyncio.create_task(sender())
    await session.start()
    outbound.put_nowait({"type": "ready"})
    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            data = message.get("bytes")
            if data is not None:
                if 1 < len(data) <= MAX_AUDIO_FRAME_BYTES:
                    session.on_audio(data[0], data[1:])
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
                        await _apply_documents(session, msg, store, user_id, llm)
                    except Exception:  # noqa: BLE001 - keep the session alive on the sample CV
                        log.exception("loading documents failed")
                        outbound.put_nowait(
                            {"type": "error", "message": "Couldn't load your CV; using the sample."}
                        )
                    outbound.put_nowait({"type": "context", **session.context.public()})
                session.on_control(msg)
    except WebSocketDisconnect:
        pass
    finally:
        await session.close()
        send_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await send_task

"""WebSocket for a live copilot session.

Client -> server
  binary: 1 byte channel (0 = interviewer / tab audio, 1 = candidate / mic)
          + 16 kHz mono PCM16 little-endian audio
  text:   {"type": "start", "session_type": "mixed" | "behavioral" | "technical"}
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

from app.api.health import SettingsDep
from app.providers.base import ProviderError
from app.providers.registry import get_llm, get_stt
from app.realtime.session import CopilotSession

log = logging.getLogger(__name__)
router = APIRouter()

MAX_AUDIO_FRAME_BYTES = 64 * 1024


@router.websocket("/ws/session")
async def session_socket(ws: WebSocket, settings: SettingsDep) -> None:
    await ws.accept()
    try:
        stt = get_stt(settings)
        llm = get_llm(settings)
    except ProviderError as exc:
        await ws.send_json({"type": "error", "message": str(exc), "retryable": False})
        await ws.close(code=1011)
        return

    outbound: asyncio.Queue[dict] = asyncio.Queue()
    session = CopilotSession(stt=stt, llm=llm, settings=settings, emit=outbound.put_nowait)

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
                if isinstance(msg, dict):
                    session.on_control(msg)
    except WebSocketDisconnect:
        pass
    finally:
        await session.close()
        send_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await send_task

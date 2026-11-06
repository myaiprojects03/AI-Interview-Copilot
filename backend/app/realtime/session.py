"""One live copilot session (one connected browser).

Audio arrives per channel (interviewer = tab audio, candidate = mic). Each channel has its
own segmenter. Final utterances go through STT in order on a per-channel worker. Partials
run separately, one at a time, and are dropped if they're stale. When an interviewer
utterance looks like a question, an answer is streamed from the LLM. A new question
cancels the answer in progress.

Outgoing events are pushed to `emit` (a non-blocking callback), so this class doesn't
depend on the WebSocket and can be tested directly.
"""

import asyncio
import contextlib
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from app.core.config import Settings
from app.providers.base import LLMProvider, ProviderError, STTProvider
from app.realtime.audio import pcm_to_wav
from app.realtime.factcheck import unverified_figures
from app.realtime.prompts import SAMPLE_CV, SessionType, build_messages
from app.realtime.questions import is_noise, is_question, normalize
from app.realtime.vad import (
    PartialAudio,
    SpeechDiscarded,
    SpeechStart,
    UtteranceEnd,
    VadConfig,
    VadSegmenter,
)

log = logging.getLogger(__name__)

INTERVIEWER = 0
CANDIDATE = 1
# A second interviewer question this soon after the first, before the candidate has spoken,
# is treated as part of the same question ("Tell me about a time ... How did you handle it?").
FOLLOW_UP_WINDOW_S = 6.0
CHANNEL_NAMES = {INTERVIEWER: "interviewer", CANDIDATE: "candidate"}

Emit = Callable[[dict], None]


@dataclass
class _FinalJob:
    utterance_id: int
    pcm: bytes
    speech_end: float  # time.monotonic() when the speaker actually stopped


@dataclass
class _Channel:
    id: int
    name: str
    segmenter: VadSegmenter
    partials: bool
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    worker: asyncio.Task | None = None
    partial_task: asyncio.Task | None = None
    finalized: set[int] = field(default_factory=set)


@dataclass
class _Answer:
    id: int
    question: str
    task: asyncio.Task


class CopilotSession:
    def __init__(
        self,
        *,
        stt: STTProvider,
        llm: LLMProvider,
        settings: Settings,
        emit: Emit,
        cv_text: str = SAMPLE_CV,
    ):
        self._stt = stt
        self._llm = llm
        self._settings = settings
        self._emit = emit
        self._cv_text = cv_text
        self.session_type: SessionType = "mixed"
        partial_ms = settings.stt_partial_interval_ms or None
        self._channels = {
            cid: _Channel(
                id=cid,
                name=name,
                segmenter=VadSegmenter(
                    VadConfig(
                        silence_ms=settings.vad_silence_ms,
                        threshold_db=settings.vad_threshold_db,
                        partial_interval_ms=partial_ms if cid == INTERVIEWER else None,
                    )
                ),
                partials=partial_ms is not None and cid == INTERVIEWER,
            )
            for cid, name in CHANNEL_NAMES.items()
        }
        self._pending_question: deque[str] = deque(maxlen=4)
        self._last_interviewer_text: str | None = None
        self._transcript: deque[str] = deque(maxlen=12)
        self._answer: _Answer | None = None
        self._last_question: str | None = None
        self._last_auto_question_at: float | None = None
        self._candidate_spoke = False
        self._next_answer_id = 1
        self._closed = False

    # ---- lifecycle -------------------------------------------------------------------

    async def start(self) -> None:
        for ch in self._channels.values():
            ch.worker = asyncio.create_task(self._final_worker(ch))

    async def close(self) -> None:
        self._closed = True
        tasks = [self._answer.task] if self._answer else []
        for ch in self._channels.values():
            tasks += [t for t in (ch.worker, ch.partial_task) if t]
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t

    # ---- input -----------------------------------------------------------------------

    def on_audio(self, channel_id: int, pcm: bytes) -> None:
        ch = self._channels.get(channel_id)
        if ch is None or self._closed:
            return
        for event in ch.segmenter.feed(pcm):
            self._handle_vad_event(ch, event)

    def on_control(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind in ("start", "set_session_type"):
            value = msg.get("session_type")
            if value in ("mixed", "behavioral", "technical"):
                self.session_type = value
        elif kind == "pause":
            for ch in self._channels.values():
                ch.segmenter.reset()
        elif kind == "answer_now":
            question = " ".join(self._pending_question) or self._last_interviewer_text
            if not question:
                self._emit({"type": "error", "message": "No interviewer question heard yet."})
                return
            self._pending_question.clear()
            self._start_answer(question, timings={})
        elif kind == "regenerate":
            if self._last_question:
                self._start_answer(self._last_question, timings={})
        elif kind == "stop_answer":
            if self._answer:
                self._answer.task.cancel()

    # ---- VAD -> STT ------------------------------------------------------------------

    def _handle_vad_event(self, ch: _Channel, event) -> None:
        if isinstance(event, SpeechStart):
            self._emit({"type": "speech", "channel": ch.name, "active": True})
        elif isinstance(event, PartialAudio):
            if ch.partials and (ch.partial_task is None or ch.partial_task.done()):
                ch.partial_task = asyncio.create_task(self._run_partial(ch, event))
        elif isinstance(event, UtteranceEnd):
            self._emit({"type": "speech", "channel": ch.name, "active": False})
            speech_end = time.monotonic() - event.trailing_silence_ms / 1000
            ch.queue.put_nowait(_FinalJob(event.utterance_id, event.pcm, speech_end))
        elif isinstance(event, SpeechDiscarded):
            self._emit({"type": "speech", "channel": ch.name, "active": False})

    async def _run_partial(self, ch: _Channel, event: PartialAudio) -> None:
        try:
            result = await self._stt.transcribe(pcm_to_wav(event.pcm))
        except ProviderError as exc:
            log.info("partial transcription failed: %s", exc)
            return
        text = normalize(result.text)
        if event.utterance_id in ch.finalized or is_noise(text):
            return
        self._emit(
            {
                "type": "transcript",
                "channel": ch.name,
                "utterance_id": event.utterance_id,
                "text": text,
                "final": False,
            }
        )

    async def _final_worker(self, ch: _Channel) -> None:
        while True:
            job: _FinalJob = await ch.queue.get()
            ch.finalized.add(job.utterance_id)
            t0 = time.monotonic()
            try:
                result = await self._stt.transcribe(pcm_to_wav(job.pcm))
            except ProviderError as exc:
                self._emit(
                    {
                        "type": "error",
                        "message": f"Transcription failed: {exc}",
                        "retryable": True,
                    }
                )
                self._emit_discard(ch, job.utterance_id)
                continue
            stt_ms = round((time.monotonic() - t0) * 1000)
            text = normalize(result.text)
            if is_noise(text):
                self._emit_discard(ch, job.utterance_id)
                continue
            self._transcript.append(f"{ch.name.capitalize()}: {text}")
            self._emit(
                {
                    "type": "transcript",
                    "channel": ch.name,
                    "utterance_id": job.utterance_id,
                    "text": text,
                    "final": True,
                    "stt_ms": stt_ms,
                }
            )
            if ch.id == INTERVIEWER:
                self._on_interviewer_final(text, job.speech_end, stt_ms)
            else:
                self._candidate_spoke = True

    def _emit_discard(self, ch: _Channel, utterance_id: int) -> None:
        self._emit({"type": "transcript_discard", "channel": ch.name, "utterance_id": utterance_id})

    # ---- questions -> answers --------------------------------------------------------

    def _on_interviewer_final(self, text: str, speech_end: float, stt_ms: int) -> None:
        self._last_interviewer_text = text
        self._pending_question.append(text)
        if not is_question(text):
            return
        question = " ".join(self._pending_question)
        self._pending_question.clear()
        now = time.monotonic()
        if (
            self._last_question
            and self._last_auto_question_at is not None
            and now - self._last_auto_question_at < FOLLOW_UP_WINDOW_S
            and not self._candidate_spoke
        ):
            question = f"{self._last_question} {question}"
        self._last_auto_question_at = now
        self._candidate_spoke = False
        self._start_answer(question, timings={"stt_ms": stt_ms, "_speech_end": speech_end})

    def _start_answer(self, question: str, timings: dict) -> None:
        if self._answer and not self._answer.task.done():
            self._answer.task.cancel()
        answer_id = self._next_answer_id
        self._next_answer_id += 1
        self._last_question = question
        task = asyncio.create_task(self._run_answer(answer_id, question, timings))
        self._answer = _Answer(answer_id, question, task)

    async def _run_answer(self, answer_id: int, question: str, timings: dict) -> None:
        speech_end = timings.pop("_speech_end", None)
        self._emit({"type": "suggestion_start", "id": answer_id, "question": question})
        messages = build_messages(
            question,
            cv_text=self._cv_text,
            session_type=self.session_type,
            recent_transcript=list(self._transcript)[:-1],
        )
        t0 = time.monotonic()
        status = "done"
        text = ""
        try:
            async for delta in self._llm.stream_chat(
                messages, max_tokens=self._settings.answer_max_tokens
            ):
                text += delta
                if "llm_first_token_ms" not in timings:
                    now = time.monotonic()
                    timings["llm_first_token_ms"] = round((now - t0) * 1000)
                    if speech_end is not None:
                        timings["speech_end_to_first_token_ms"] = round((now - speech_end) * 1000)
                self._emit({"type": "suggestion_delta", "id": answer_id, "text": delta})
        except asyncio.CancelledError:
            status = "stopped"
            raise
        except ProviderError as exc:
            status = "error"
            self._emit(
                {"type": "error", "message": f"Answer failed: {exc}", "retryable": True}
            )
        finally:
            timings["llm_total_ms"] = round((time.monotonic() - t0) * 1000)
            self._emit(
                {
                    "type": "suggestion_end",
                    "id": answer_id,
                    "status": status,
                    "timings": timings,
                    "unverified": unverified_figures(text, self._cv_text),
                }
            )

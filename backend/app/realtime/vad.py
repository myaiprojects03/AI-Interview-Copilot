"""Energy-based voice activity detection and endpointing.

Cuts a continuous PCM stream into utterances: speech starts after a few loud frames and
ends after `silence_ms` of quiet. Time is counted in audio samples, not wall-clock time,
so the segmenter is deterministic and easy to test.

The speech threshold adapts to background noise: the noise floor drops quickly to quiet
levels and rises slowly, so steady room noise stops counting as speech.
"""

from collections import deque
from dataclasses import dataclass

from app.realtime.audio import SAMPLE_RATE, ms_to_bytes, rms_dbfs


@dataclass(frozen=True)
class VadConfig:
    sample_rate: int = SAMPLE_RATE
    frame_ms: int = 20
    threshold_db: float = -45.0  # never treat anything quieter than this as speech
    noise_margin_db: float = 10.0  # speech must be this much louder than the noise floor
    start_frames: int = 3  # consecutive loud frames needed to start an utterance
    silence_ms: int = 800  # quiet time that ends an utterance (endpointing)
    pre_roll_ms: int = 300  # audio kept from before speech started
    min_speech_ms: int = 300  # shorter bursts (clicks, coughs) are discarded
    max_utterance_ms: int = 20000  # force a cut on very long speech
    partial_interval_ms: int | None = 2000  # emit in-progress audio this often; None = off
    noise_rise_rate: float = 0.005


@dataclass(frozen=True)
class SpeechStart:
    utterance_id: int


@dataclass(frozen=True)
class PartialAudio:
    utterance_id: int
    pcm: bytes


@dataclass(frozen=True)
class UtteranceEnd:
    utterance_id: int
    pcm: bytes
    speech_ms: int
    trailing_silence_ms: int


@dataclass(frozen=True)
class SpeechDiscarded:
    utterance_id: int


VadEvent = SpeechStart | PartialAudio | UtteranceEnd | SpeechDiscarded


class VadSegmenter:
    def __init__(self, config: VadConfig | None = None):
        self.cfg = config or VadConfig()
        self._frame_bytes = ms_to_bytes(self.cfg.frame_ms, self.cfg.sample_rate)
        self._pending = bytearray()
        pre_roll_frames = max(1, self.cfg.pre_roll_ms // self.cfg.frame_ms)
        self._pre_roll: deque[bytes] = deque(maxlen=pre_roll_frames)
        self._noise_db = -60.0
        self._next_id = 1
        self._reset_utterance()

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    def _reset_utterance(self) -> None:
        self._in_speech = False
        self._utterance = bytearray()
        self._utterance_id = 0
        self._loud_run = 0
        self._speech_frames = 0
        self._silence_frames = 0
        self._frames_since_partial = 0

    def reset(self) -> None:
        """Drop any in-progress speech (used when the user pauses)."""
        self._pending.clear()
        self._pre_roll.clear()
        self._reset_utterance()

    def feed(self, pcm: bytes) -> list[VadEvent]:
        self._pending += pcm
        events: list[VadEvent] = []
        fb = self._frame_bytes
        while len(self._pending) >= fb:
            frame = bytes(self._pending[:fb])
            del self._pending[:fb]
            events.extend(self._process(frame))
        return events

    def flush(self) -> list[VadEvent]:
        """End any in-progress utterance (used when the stream stops)."""
        return [self._finish()] if self._in_speech else []

    def _is_loud(self, db: float) -> bool:
        threshold = max(self.cfg.threshold_db, self._noise_db + self.cfg.noise_margin_db)
        return db >= threshold

    def _track_noise(self, db: float) -> None:
        if db < self._noise_db:
            self._noise_db = max(db, -90.0)
        else:
            self._noise_db += self.cfg.noise_rise_rate * (db - self._noise_db)

    def _process(self, frame: bytes) -> list[VadEvent]:
        db = rms_dbfs(frame)
        loud = self._is_loud(db)
        self._track_noise(db)
        cfg = self.cfg

        if not self._in_speech:
            self._loud_run = self._loud_run + 1 if loud else 0
            self._pre_roll.append(frame)
            if self._loud_run < cfg.start_frames:
                return []
            self._in_speech = True
            self._utterance_id = self._next_id
            self._next_id += 1
            self._utterance = bytearray(b"".join(self._pre_roll))
            self._pre_roll.clear()
            self._speech_frames = self._loud_run
            self._silence_frames = 0
            self._frames_since_partial = 0
            return [SpeechStart(self._utterance_id)]

        self._utterance += frame
        if loud:
            self._speech_frames += 1
            self._silence_frames = 0
        else:
            self._silence_frames += 1
        self._frames_since_partial += 1

        if self._silence_frames * cfg.frame_ms >= cfg.silence_ms:
            return [self._finish()]
        if len(self._utterance) >= ms_to_bytes(cfg.max_utterance_ms, cfg.sample_rate):
            return [self._finish()]
        if (
            cfg.partial_interval_ms
            and self._frames_since_partial * cfg.frame_ms >= cfg.partial_interval_ms
            and self._silence_frames == 0
        ):
            self._frames_since_partial = 0
            return [PartialAudio(self._utterance_id, bytes(self._utterance))]
        return []

    def _finish(self) -> VadEvent:
        cfg = self.cfg
        utterance_id = self._utterance_id
        speech_ms = self._speech_frames * cfg.frame_ms
        trailing_ms = self._silence_frames * cfg.frame_ms
        # Keep a short tail of the trailing silence; Whisper does not need all of it.
        keep_tail = min(trailing_ms, 200)
        cut = ms_to_bytes(trailing_ms - keep_tail, cfg.sample_rate)
        pcm = bytes(self._utterance[: len(self._utterance) - cut] if cut else self._utterance)
        self._reset_utterance()
        if speech_ms < cfg.min_speech_ms:
            return SpeechDiscarded(utterance_id)
        return UtteranceEnd(utterance_id, pcm, speech_ms, trailing_ms)

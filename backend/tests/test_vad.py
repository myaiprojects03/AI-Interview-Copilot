from app.realtime.audio import rms_dbfs
from app.realtime.vad import (
    PartialAudio,
    SpeechDiscarded,
    SpeechStart,
    UtteranceEnd,
    VadConfig,
    VadSegmenter,
)
from tests.audio_utils import chunks, silence, tone


def run(seg: VadSegmenter, pcm: bytes) -> list:
    events = []
    for c in chunks(pcm):
        events += seg.feed(c)
    return events


def test_rms_levels():
    assert rms_dbfs(silence(20)) == -100.0
    assert -20 < rms_dbfs(tone(20, amplitude=8000)) < -10


def test_silence_produces_nothing():
    assert run(VadSegmenter(), silence(3000)) == []


def test_speech_then_silence_is_one_utterance():
    events = run(VadSegmenter(), silence(500) + tone(1000) + silence(1000))
    kinds = [type(e) for e in events]
    assert kinds == [SpeechStart, UtteranceEnd]
    end = events[1]
    assert 900 <= end.speech_ms <= 1000
    assert end.trailing_silence_ms >= 800
    # Pre-roll + speech + at most 200 ms of kept tail.
    assert len(end.pcm) <= (300 + 1000 + 200) * 32 + 640


def test_pause_shorter_than_endpoint_keeps_one_utterance():
    events = run(VadSegmenter(), tone(800) + silence(400) + tone(800) + silence(1000))
    assert [type(e) for e in events] == [SpeechStart, UtteranceEnd]


def test_two_utterances_get_distinct_ids():
    events = run(VadSegmenter(), tone(600) + silence(1000) + tone(600) + silence(1000))
    ends = [e for e in events if isinstance(e, UtteranceEnd)]
    assert [e.utterance_id for e in ends] == [1, 2]


def test_short_click_is_discarded():
    events = run(VadSegmenter(), tone(100) + silence(1000))
    assert [type(e) for e in events] == [SpeechStart, SpeechDiscarded]


def test_partials_emitted_during_long_speech():
    seg = VadSegmenter(VadConfig(partial_interval_ms=1000))
    events = run(seg, tone(3500) + silence(1000))
    partials = [e for e in events if isinstance(e, PartialAudio)]
    assert len(partials) == 3
    assert len(partials[1].pcm) > len(partials[0].pcm)


def test_partials_off():
    seg = VadSegmenter(VadConfig(partial_interval_ms=None))
    assert not any(isinstance(e, PartialAudio) for e in run(seg, tone(5000) + silence(1000)))


def test_max_utterance_forces_cut():
    seg = VadSegmenter(VadConfig(max_utterance_ms=2000, partial_interval_ms=None))
    events = run(seg, tone(4500))
    assert sum(isinstance(e, UtteranceEnd) for e in events) == 2


def test_reset_drops_in_progress_speech():
    seg = VadSegmenter()
    run(seg, tone(500))
    assert seg.in_speech
    seg.reset()
    assert not seg.in_speech
    assert run(seg, silence(1000)) == []

import asyncio
from collections.abc import AsyncIterator

from app.core.config import Settings
from app.providers.base import ChatMessage, LLMProvider, STTProvider, Transcript
from app.providers.llm.fake import FakeLLM
from app.realtime.session import CANDIDATE, INTERVIEWER, CopilotSession
from tests.audio_utils import chunks, silence, tone


class ScriptedSTT(STTProvider):
    name = "scripted"

    def __init__(self, texts: list[str]):
        self._texts = list(texts)

    async def transcribe(self, audio, *, filename="audio.wav", language="en") -> Transcript:
        return Transcript(self._texts.pop(0) if self._texts else "")


class SlowLLM(LLMProvider):
    name = "slow"

    async def stream_chat(self, messages: list[ChatMessage], **kw) -> AsyncIterator[str]:
        for word in ["one ", "two ", "three "]:
            await asyncio.sleep(0.2)
            yield word


def make(stt, llm=None, **overrides):
    events: list[dict] = []
    settings = Settings(_env_file=None, stt_partial_interval_ms=0, **overrides)
    session = CopilotSession(stt=stt, llm=llm or FakeLLM(), settings=settings, emit=events.append)
    return session, events


def speak(session, channel, ms=800):
    for c in chunks(tone(ms) + silence(1000)):
        session.on_audio(channel, c)


async def wait_for(events, predicate, timeout=3.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if any(predicate(e) for e in events):
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"timed out; events={events}")


async def test_interviewer_question_streams_an_answer():
    session, events = make(ScriptedSTT(["Tell me about yourself."]))
    await session.start()
    speak(session, INTERVIEWER)
    await wait_for(events, lambda e: e["type"] == "suggestion_end")
    await session.close()

    final = next(e for e in events if e["type"] == "transcript")
    assert final == {
        "type": "transcript",
        "channel": "interviewer",
        "utterance_id": 1,
        "text": "Tell me about yourself.",
        "final": True,
        "stt_ms": final["stt_ms"],
    }
    start = next(e for e in events if e["type"] == "suggestion_start")
    assert start["question"] == "Tell me about yourself."
    text = "".join(e["text"] for e in events if e["type"] == "suggestion_delta")
    assert "fake suggestion" in text
    end = next(e for e in events if e["type"] == "suggestion_end")
    assert end["status"] == "done"
    assert {"stt_ms", "llm_first_token_ms", "speech_end_to_first_token_ms"} <= end["timings"].keys()


async def test_candidate_speech_never_triggers_an_answer():
    session, events = make(ScriptedSTT(["How would I design this?"]))
    await session.start()
    speak(session, CANDIDATE)
    await wait_for(events, lambda e: e["type"] == "transcript")
    await asyncio.sleep(0.1)
    await session.close()
    assert events[-1]["channel"] == "candidate"
    assert not any(e["type"] == "suggestion_start" for e in events)


async def test_preamble_is_joined_with_the_question():
    session, events = make(ScriptedSTT(["I see you worked at Kitecart.", "Why did you leave?"]))
    await session.start()
    speak(session, INTERVIEWER)
    speak(session, INTERVIEWER)
    await wait_for(events, lambda e: e["type"] == "suggestion_start")
    await session.close()
    start = next(e for e in events if e["type"] == "suggestion_start")
    assert start["question"] == "I see you worked at Kitecart. Why did you leave?"


async def test_whisper_hallucination_is_discarded():
    session, events = make(ScriptedSTT(["Thank you."]))
    await session.start()
    speak(session, INTERVIEWER)
    await wait_for(events, lambda e: e["type"] == "transcript_discard")
    await session.close()
    assert not any(e["type"] == "transcript" for e in events)


async def test_new_question_cancels_the_running_answer():
    session, events = make(ScriptedSTT(["What is Redis?", "Why do you want this job?"]), SlowLLM())
    await session.start()
    speak(session, INTERVIEWER)
    await wait_for(events, lambda e: e["type"] == "suggestion_start")
    speak(session, INTERVIEWER)
    await wait_for(events, lambda e: e["type"] == "suggestion_end" and e["id"] == 2)
    await session.close()
    ends = {e["id"]: e["status"] for e in events if e["type"] == "suggestion_end"}
    assert ends == {1: "stopped", 2: "done"}


async def test_quick_follow_up_is_merged_into_the_previous_question():
    stt = ScriptedSTT(["Tell me about a time you disagreed with a team.", "How did you handle it?"])
    session, events = make(stt)
    await session.start()
    speak(session, INTERVIEWER)
    speak(session, INTERVIEWER)
    await wait_for(events, lambda e: e["type"] == "suggestion_end" and e["id"] == 2)
    await session.close()
    starts = [e["question"] for e in events if e["type"] == "suggestion_start"]
    assert starts[-1] == "Tell me about a time you disagreed with a team. How did you handle it?"


async def test_candidate_answer_stops_follow_up_merge():
    stt = ScriptedSTT(["What is Redis?", "It's an in-memory store.", "Why do you want this job?"])
    session, events = make(stt)
    await session.start()
    speak(session, INTERVIEWER)
    await wait_for(events, lambda e: e["type"] == "suggestion_end")
    speak(session, CANDIDATE)
    await wait_for(events, lambda e: e.get("channel") == "candidate" and e["type"] == "transcript")
    speak(session, INTERVIEWER)
    await wait_for(events, lambda e: e["type"] == "suggestion_end" and e["id"] == 2)
    await session.close()
    starts = [e["question"] for e in events if e["type"] == "suggestion_start"]
    assert starts == ["What is Redis?", "Why do you want this job?"]


async def test_figures_from_the_question_are_not_flagged():
    llm = FakeLLM("In five years I want to lead a team, and in 3 years ship a 40% faster API.")
    session, events = make(ScriptedSTT(["Where do you see yourself in five years?"]), llm)
    await session.start()
    speak(session, INTERVIEWER)
    await wait_for(events, lambda e: e["type"] == "suggestion_end")
    await session.close()
    end = next(e for e in events if e["type"] == "suggestion_end")
    assert end["unverified"] == ["3 years", "40%"]


async def test_gap_skills_mentioned_in_an_answer_are_reported():
    from app.answer.gaps import SkillGap
    from app.answer.retrieval import InterviewContext

    llm = FakeLLM("I deployed services on AWS and know Redis well.")
    session, events = make(ScriptedSTT(["Why should we hire you?"]), llm)
    session.context = InterviewContext(
        sample_cv_text="Redis caching expert.", gaps=[SkillGap("AWS", ("AWS",))]
    )
    await session.start()
    speak(session, INTERVIEWER)
    await wait_for(events, lambda e: e["type"] == "suggestion_end")
    await session.close()
    end = next(e for e in events if e["type"] == "suggestion_end")
    assert end["gap_mentions"] == [{"skill": "AWS", "matches": ["AWS"]}]


async def test_controls_stop_regenerate_and_answer_now():
    session, events = make(ScriptedSTT(["That sounds good."]), SlowLLM())
    await session.start()

    session.on_control({"type": "answer_now"})
    assert events[-1]["type"] == "error"

    speak(session, INTERVIEWER)  # not a question, so no automatic answer
    await wait_for(events, lambda e: e["type"] == "transcript")
    assert not any(e["type"] == "suggestion_start" for e in events)

    session.on_control({"type": "answer_now"})
    await wait_for(events, lambda e: e["type"] == "suggestion_delta")
    session.on_control({"type": "stop_answer"})
    await wait_for(events, lambda e: e["type"] == "suggestion_end")
    assert events[-1]["status"] == "stopped"

    session.on_control({"type": "regenerate"})
    await wait_for(events, lambda e: e["type"] == "suggestion_end" and e["id"] == 2)
    await session.close()
    starts = [e["question"] for e in events if e["type"] == "suggestion_start"]
    assert starts == ["That sounds good.", "That sounds good."]

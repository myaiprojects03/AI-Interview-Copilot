"""End-to-end tests on the recorded mock interview, with the real AI providers.

Streams parts of frontend/public/demo/mock-interview.wav through the WebSocket at real
speed: real Groq speech-to-text, question detection, classification and real Groq answers.
Covers a general, a behavioral (with its follow-up merged) and a technical question.

They use real API calls (free-tier quota), so they only run when asked:
    RUN_LIVE_TESTS=1 pytest tests/test_live_interview.py -s
"""

import json
import os
import time
import wave
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import create_app
from tests.audio_utils import silence

WAV = Path(__file__).resolve().parents[2] / "frontend/public/demo/mock-interview.wav"
pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_TESTS") != "1", reason="set RUN_LIVE_TESTS=1 to call real providers"
)


def live_settings() -> Settings:
    real = Settings()  # reads backend/.env for the Groq key and model
    assert real.groq_api_key, "GROQ_API_KEY must be set in backend/.env"
    return real.model_copy(update={
        "environment": "test", "supabase_url": None, "supabase_jwt_secret": None,
        "database_url": None, "embedding_provider": "fake", "billing_provider": "fake",
        "stt_partial_interval_ms": 0,  # no partials: keeps us inside the free-tier rate limit
    })


def question_of(events: list[dict], answer_id: int) -> str:
    return next(
        (e["question"] for e in events
         if e["type"] == "suggestion_start" and e["id"] == answer_id),
        "",
    )


def play(start_s: float, seconds: float, done: Callable[[dict, list[dict]], bool]) -> list[dict]:
    """Stream part of the recording AT REAL SPEED (the follow-up merge measures real time),
    then read events until done(event, events_so_far) is true."""
    settings = live_settings()
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    with wave.open(str(WAV), "rb") as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
        w.setpos(int(16000 * start_s))
        pcm = w.readframes(int(16000 * seconds)) + silence(1500)

    events: list[dict] = []
    with TestClient(app) as client, client.websocket_connect("/ws/session") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_text(json.dumps({"type": "start", "cv_id": None, "jd_id": None}))
        t0 = time.monotonic()
        for n, i in enumerate(range(0, len(pcm), 3200)):  # 100 ms chunks
            ws.send_bytes(bytes([0]) + pcm[i : i + 3200])
            time.sleep(max(0.0, t0 + (n + 1) * 0.1 - time.monotonic()))
        while True:
            e = ws.receive_json()
            events.append(e)
            if e["type"] == "error":
                pytest.fail(e["message"])
            if done(e, events):
                return events


def answer_text(events: list[dict], answer_id: int) -> str:
    return "".join(
        e["text"] for e in events if e["type"] == "suggestion_delta" and e["id"] == answer_id
    )


def finished(phrase: str) -> Callable[[dict, list[dict]], bool]:
    def check(e: dict, events: list[dict]) -> bool:
        return (
            e["type"] == "suggestion_end"
            and e["status"] == "done"
            and phrase in question_of(events, e["id"]).lower()
        )

    return check


def test_general_and_behavioral_questions():
    """0-26 s: "Can you tell me a little about yourself?" (general), then "Tell me about a
    time you had a disagreement... How did you handle it?" (behavioral, follow-up merged)."""
    events = play(0, 26, finished("handle it"))

    finals = [e["text"].lower() for e in events if e["type"] == "transcript" and e["final"]]
    assert any("about yourself" in t for t in finals), finals
    assert any("disagreement" in t for t in finals), finals

    starts = {e["id"]: e for e in events if e["type"] == "suggestion_start"}
    ends = {e["id"]: e for e in events if e["type"] == "suggestion_end"}
    print("\nquestions:")
    for i, s in starts.items():
        print(f"  {s['question_type']:10} {ends[i]['status']:8} ...{s['question'][-60:]}")

    first = starts[min(starts)]
    assert first["question_type"] == "general"
    assert "yourself" in first["question"].lower()

    merged = starts[max(starts)]
    assert merged["question_type"] == "behavioral"
    assert "disagreement" in merged["question"].lower()
    assert "handle it" in merged["question"].lower()
    text = answer_text(events, merged["id"])
    for label in ("**S:**", "**T:**", "**A:**", "**R:**"):
        assert label in text, text

    for e in ends.values():
        if e["status"] == "done":
            t = e["timings"]
            print("  timings:", {k: t.get(k) for k in (
                "stt_ms", "llm_first_token_ms", "speech_end_to_first_token_ms")})
            assert t["llm_first_token_ms"] < 5000


def test_technical_question():
    """32.5-45.5 s: "How would you design a rate limiter for a public API?" (technical)."""
    events = play(32.5, 13, finished("rate"))
    final = [e for e in events if e["type"] == "suggestion_start"][-1]
    text = answer_text(events, final["id"])
    print("\ntechnical question:", final["question"])
    assert final["question_type"] == "technical"
    assert text.strip()
    assert "**S:**" not in text

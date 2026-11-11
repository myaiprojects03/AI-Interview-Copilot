"""Behaviour needed to run on Vercel: connection time limits, carrying context across a
connection switch, and loading the embedding model bundled at build time."""

import json
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import BACKEND_DIR, Settings, get_settings
from app.main import create_app
from app.providers.base import ChatMessage, LLMProvider
from app.realtime.session import INTERVIEWER, CopilotSession
from tests.audio_utils import chunks, silence, tone


def client_with(**overrides) -> TestClient:
    settings = Settings(_env_file=None, environment="test", llm_provider="fake",
                        stt_provider="fake", embedding_provider="fake", database_url=None,
                        **overrides)
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def test_ready_announces_the_limit_and_the_server_cuts_at_it():
    with client_with(ws_max_seconds=1) as client, client.websocket_connect("/ws/session") as ws:
        assert ws.receive_json() == {"type": "ready", "max_seconds": 1}
        ws.receive_json()  # usage
        with pytest.raises(WebSocketDisconnect) as closed:
            for _ in range(50):
                ws.receive_json()
    assert closed.value.code == 4408  # the browser reconnects at once on this code


def test_no_limit_by_default_locally():
    with client_with() as client, client.websocket_connect("/ws/session") as ws:
        assert ws.receive_json() == {"type": "ready"}


def test_vercel_defaults_to_300_seconds(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    assert Settings(_env_file=None).ws_limit_seconds == 300
    assert Settings(_env_file=None, ws_max_seconds=120).ws_limit_seconds == 120
    monkeypatch.delenv("VERCEL")
    assert Settings(_env_file=None).ws_limit_seconds is None


def test_bundled_model_folder(tmp_path):
    assert Settings(_env_file=None, embedding_cache_dir=str(tmp_path)).model_cache_dir == tmp_path
    rel = Settings(_env_file=None, embedding_cache_dir="models").model_cache_dir
    assert rel == BACKEND_DIR / "models"


class RecordingLLM(LLMProvider):
    name = "recording"

    def __init__(self):
        self.prompts: list[str] = []

    async def stream_chat(self, messages: list[ChatMessage], **kw) -> AsyncIterator[str]:
        self.prompts.append(messages[-1].content)
        yield "ok"


def test_recent_transcript_is_carried_to_a_fresh_connection(monkeypatch):
    """After a switch, the new connection's answers still see the earlier conversation."""
    llm = RecordingLLM()
    monkeypatch.setattr("app.api.realtime.get_llm", lambda settings: llm)
    with client_with() as client, client.websocket_connect("/ws/session") as ws:
        ws.receive_json()
        ws.receive_json()
        ws.send_text(json.dumps({
            "type": "start",
            "recent": ["Interviewer: Tell me about Brightlane.", "Candidate: I led payments.", 42],
        }))
        for c in chunks(tone(1000) + silence(1000)):
            ws.send_bytes(bytes([INTERVIEWER]) + c)
        while ws.receive_json()["type"] != "suggestion_end":
            pass
    prompt = llm.prompts[0]
    assert "Interviewer: Tell me about Brightlane." in prompt
    assert "Candidate: I led payments." in prompt


def test_seed_transcript_keeps_only_the_last_lines():
    session = CopilotSession(stt=None, llm=None, settings=Settings(_env_file=None),
                             emit=lambda e: None)
    session.seed_transcript([f"line {i}" for i in range(20)])
    assert list(session._transcript) == [f"line {i}" for i in range(8, 20)]


@pytest.mark.skipif(not (BACKEND_DIR / "models").is_dir(),
                    reason="run scripts/fetch_model.py first (the Vercel build does)")
async def test_bundled_model_loads_offline():
    from app.providers.embeddings.local import LocalEmbeddings

    emb = LocalEmbeddings(cache_dir=BACKEND_DIR / "models")
    vector = await emb.embed_query("design a rate limiter")
    assert len(vector) == 384


def test_flush_finishes_a_sentence_cut_short_by_a_switch():
    """The browser switched connections mid-sentence: the old one transcribes what it has."""
    with client_with() as client, client.websocket_connect("/ws/session") as ws:
        ws.receive_json()
        ws.receive_json()
        ws.send_text(json.dumps({"type": "start"}))
        for c in chunks(tone(900)):  # speech that never reaches its pause
            ws.send_bytes(bytes([INTERVIEWER]) + c)
        ws.send_text(json.dumps({"type": "flush"}))
        events = []
        while True:
            e = ws.receive_json()
            events.append(e)
            if e["type"] == "transcript" and e["final"]:
                break
    assert e["text"] == "Tell me about yourself."

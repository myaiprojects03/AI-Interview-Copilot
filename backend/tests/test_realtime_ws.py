import json

from app.realtime.session import INTERVIEWER
from tests.audio_utils import chunks, silence, tone

CV = """Priya Shah
EXPERIENCE
Machine Learning Engineer, Orbital Health (2021 to present)
- Built a triage model in PyTorch that cut nurse review time by 35%.
- Deployed models on Kubernetes with canary releases.
EDUCATION
MSc Artificial Intelligence, University of Edinburgh, 2020
"""


def receive_until(ws, kind: str, limit: int = 200) -> list[dict]:
    events = []
    for _ in range(limit):
        event = ws.receive_json()
        events.append(event)
        if event["type"] == kind:
            return events
    raise AssertionError(f"no {kind!r} in {events}")


def ask(ws, start: dict) -> list[dict]:
    assert ws.receive_json() == {"type": "ready"}
    ws.send_text(json.dumps(start))
    for c in chunks(tone(1000) + silence(1000)):
        ws.send_bytes(bytes([INTERVIEWER]) + c)
    return receive_until(ws, "suggestion_end")


def test_websocket_end_to_end_with_fake_providers(client):
    with client.websocket_connect("/ws/session") as ws:
        assert ws.receive_json() == {"type": "ready"}
        ws.send_text(json.dumps({"type": "start", "session_type": "behavioral"}))
        ws.send_bytes(b"x")  # too short, ignored
        ws.send_text("not json")  # ignored
        for c in chunks(tone(1000) + silence(1000)):
            ws.send_bytes(bytes([INTERVIEWER]) + c)
        events = receive_until(ws, "suggestion_end")

    types = [e["type"] for e in events]
    assert events[0] == {
        "type": "context", "cv": None, "jd": None, "using_sample_cv": True, "gaps": []
    }
    assert events[1]["type"] == "speech" and events[1]["active"] is True
    assert "transcript" in types
    start = next(e for e in events if e["type"] == "suggestion_start")
    assert start["question_type"] == "general"  # fake STT says "Tell me about yourself."
    assert types.index("suggestion_start") < types.index("suggestion_delta")
    assert events[-1]["status"] == "done"
    assert "retrieval_ms" in events[-1]["timings"]


def test_session_uses_uploaded_cv(client):
    r = client.post("/documents", data={"kind": "cv", "text": CV})
    assert r.status_code == 201, r.text
    cv_id = r.json()["id"]

    with client.websocket_connect("/ws/session") as ws:
        events = ask(ws, {"type": "start", "cv_id": cv_id, "jd_id": None})

    context = events[0]
    assert context["cv"] == {"id": cv_id, "title": "CV: Priya Shah"}
    assert context["using_sample_cv"] is False
    start = next(e for e in events if e["type"] == "suggestion_start")
    assert any("Orbital Health" in s for s in start["sources"])


def test_unknown_cv_id_falls_back_to_sample(client):
    with client.websocket_connect("/ws/session") as ws:
        events = ask(ws, {"type": "start", "cv_id": "not-a-real-id"})
    assert events[0]["using_sample_cv"] is True


def test_websocket_reports_missing_key(client, settings):
    settings.llm_provider = "groq"
    settings.groq_api_key = None
    with client.websocket_connect("/ws/session") as ws:
        event = ws.receive_json()
    assert event["type"] == "error"
    assert "GROQ_API_KEY" in event["message"]

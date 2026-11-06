import json

from app.realtime.session import INTERVIEWER
from tests.audio_utils import chunks, silence, tone


def receive_until(ws, kind: str, limit: int = 200) -> list[dict]:
    events = []
    for _ in range(limit):
        event = ws.receive_json()
        events.append(event)
        if event["type"] == kind:
            return events
    raise AssertionError(f"no {kind!r} in {events}")


def test_websocket_end_to_end_with_fake_providers(client):
    with client.websocket_connect("/ws/session") as ws:
        assert ws.receive_json() == {"type": "ready"}
        ws.send_text(json.dumps({"type": "start", "session_type": "behavioral"}))
        ws.send_bytes(b"not-json-is-ignored"[:1])  # too short, ignored
        ws.send_text("not json")  # ignored
        for c in chunks(tone(1000) + silence(1000)):
            ws.send_bytes(bytes([INTERVIEWER]) + c)
        events = receive_until(ws, "suggestion_end")

    types = [e["type"] for e in events]
    assert types[0] == "speech" and events[0]["active"] is True
    assert "transcript" in types
    assert types.index("suggestion_start") < types.index("suggestion_delta")
    assert events[-1]["status"] == "done"


def test_websocket_reports_missing_key(client, settings):
    settings.llm_provider = "groq"
    settings.groq_api_key = None
    with client.websocket_connect("/ws/session") as ws:
        event = ws.receive_json()
    assert event["type"] == "error"
    assert "GROQ_API_KEY" in event["message"]

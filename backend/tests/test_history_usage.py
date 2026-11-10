import asyncio
import json

from app.billing.plans import month_key
from app.realtime.session import CANDIDATE, INTERVIEWER
from tests.audio_utils import chunks, silence, tone
from tests.phase3_utils import auth, token


def open_session(ws, user="user-1") -> dict:
    ws.send_text(json.dumps({"type": "auth", "token": token(user)}))
    assert ws.receive_json() == {"type": "ready"}
    return ws.receive_json()  # usage


def run_question(ws):
    ws.send_text(json.dumps({"type": "start", "cv_id": None, "jd_id": None}))
    for c in chunks(tone(1000) + silence(1000)):
        ws.send_bytes(bytes([INTERVIEWER]) + c)
    for c in chunks(tone(800) + silence(1000)):
        ws.send_bytes(bytes([CANDIDATE]) + c)
    events = []
    while True:
        e = ws.receive_json()
        events.append(e)
        if e["type"] == "transcript" and e["channel"] == "candidate":
            return events


def test_session_is_saved_to_history_and_usage_is_metered(auth_client):
    with auth_client.websocket_connect("/ws/session") as ws:
        open_session(ws)
        run_question(ws)

    sessions = auth_client.get("/sessions", headers=auth()).json()
    assert len(sessions) == 1
    s = sessions[0]
    assert s["cv_title"] == "Sample CV" and s["question_count"] == 1
    assert s["seconds"] == 2  # only the interviewer channel is metered
    detail = auth_client.get(f"/sessions/{s['id']}", headers=auth()).json()
    assert [t["speaker"] for t in detail["turns"]] == ["interviewer", "candidate"]
    assert detail["answers"][0]["question"] == "Tell me about yourself."
    assert detail["answers"][0]["question_type"] == "general"

    usage = auth_client.get("/billing/me", headers=auth()).json()["usage"]
    assert usage["used_minutes"] == 0.0  # 2 s rounds to 0.0 minutes
    used = asyncio.run(auth_client.app.state.accounts.usage_seconds("user-1", month_key()))
    assert abs(used - 2.0) < 0.05

    # Other users can't see or delete it.
    assert auth_client.get("/sessions", headers=auth("bob")).json() == []
    assert auth_client.get(f"/sessions/{s['id']}", headers=auth("bob")).status_code == 404
    assert auth_client.delete(f"/sessions/{s['id']}", headers=auth("bob")).status_code == 404
    assert auth_client.delete(f"/sessions/{s['id']}", headers=auth()).status_code == 204
    assert auth_client.get("/sessions", headers=auth()).json() == []


def test_user_at_the_limit_cannot_start(auth_client):
    accounts = auth_client.app.state.accounts
    asyncio.run(accounts.add_usage("user-1", month_key(), 30 * 60))
    with auth_client.websocket_connect("/ws/session") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token()}))
        event = ws.receive_json()
    assert event["type"] == "limit_reached"
    assert "30 interview minutes" in event["message"]

    # Upgrading lifts the block.
    auth_client.post("/billing/checkout", json={"plan": "starter"}, headers=auth())
    with auth_client.websocket_connect("/ws/session") as ws:
        usage = open_session(ws)
    assert usage["remaining_seconds"] == 90 * 60


def test_session_stops_when_the_limit_is_hit_mid_interview(auth_client):
    accounts = auth_client.app.state.accounts
    asyncio.run(accounts.add_usage("user-1", month_key(), 30 * 60 - 1.0))  # 1 s left
    with auth_client.websocket_connect("/ws/session") as ws:
        assert open_session(ws)["remaining_seconds"] == 1.0
        ws.send_text(json.dumps({"type": "start"}))
        for c in chunks(tone(1500)):
            ws.send_bytes(bytes([INTERVIEWER]) + c)
        events = []
        while True:
            e = ws.receive_json()
            events.append(e)
            if e["type"] == "limit_reached":
                break
    usage_events = [e for e in events if e["type"] == "usage"]
    assert usage_events[-1]["remaining_seconds"] == 0.0


def test_delete_all_my_data(auth_client):
    h = auth()
    auth_client.post("/documents", data={"kind": "cv", "text": "Engineer. " * 40}, headers=h)
    with auth_client.websocket_connect("/ws/session") as ws:
        open_session(ws)
        run_question(ws)
    auth_client.post("/billing/checkout", json={"plan": "starter"}, headers=h)

    r = auth_client.delete("/me/data", headers=h)
    assert r.json() == {"deleted_documents": 1, "deleted_interviews": 1}
    assert auth_client.get("/documents", headers=h).json() == []
    assert auth_client.get("/sessions", headers=h).json() == []
    assert auth_client.get("/billing/me", headers=h).json()["plan"] == "starter"  # billing kept


def test_admin_latency_view(auth_client, auth_settings):
    with auth_client.websocket_connect("/ws/session") as ws:
        open_session(ws)
        run_question(ws)

    # Not an admin yet.
    assert auth_client.get("/admin/latency", headers=auth()).status_code == 403

    auth_settings.admin_emails = "Someone@else.com, u1@example.com"
    r = auth_client.get("/admin/latency?days=7", headers=auth())
    assert r.status_code == 200
    data = r.json()
    assert data["answers"] == 1 and data["statuses"] == {"done": 1}
    m = {x["key"]: x["summary"] for x in data["metrics"]}
    assert m["speech_end_to_first_token_ms"]["count"] == 1
    assert m["stt_ms"]["p50"] >= 0
    assert data["daily"][0]["count"] == 1
    recent = data["recent"][0]
    assert recent["question_type"] == "general"
    assert "question" not in recent and "answer" not in recent  # no user content

    # Saved timings come back with the interview too.
    sid = auth_client.get("/sessions", headers=auth()).json()[0]["id"]
    detail = auth_client.get(f"/sessions/{sid}", headers=auth()).json()
    assert "llm_first_token_ms" in detail["answers"][0]["timings"]


def test_reconnect_continues_the_same_interview(auth_client):
    with auth_client.websocket_connect("/ws/session") as ws:
        open_session(ws)
        events = run_question(ws)
    history_id = next(e["id"] for e in events if e["type"] == "history")

    # The browser reconnects and asks to continue that interview.
    with auth_client.websocket_connect("/ws/session") as ws:
        open_session(ws)
        ws.send_text(json.dumps({"type": "start", "history_id": history_id}))
        for c in chunks(tone(1000) + silence(1000)):
            ws.send_bytes(bytes([INTERVIEWER]) + c)
        while True:
            e = ws.receive_json()
            if e["type"] == "history":
                assert e["id"] == history_id
            if e["type"] == "suggestion_end":
                break

    sessions = auth_client.get("/sessions", headers=auth()).json()
    assert len(sessions) == 1
    assert sessions[0]["seconds"] == 4  # 2 s + 2 s, added up across connections
    assert sessions[0]["question_count"] == 2

    # Someone else can't attach to it.
    with auth_client.websocket_connect("/ws/session") as ws:
        open_session(ws, user="bob")
        ws.send_text(json.dumps({"type": "start", "history_id": history_id}))
        while True:
            e = ws.receive_json()
            if e["type"] == "history":
                assert e["id"] != history_id
                break

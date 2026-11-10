import json

import pytest

from app.core.auth import AuthError, TokenVerifier
from app.core.config import Settings
from tests.phase3_utils import auth, token


async def test_verifier_accepts_valid_and_rejects_bad_tokens(auth_settings):
    v = TokenVerifier(auth_settings)
    user = await v.verify(token("abc", "a@b.c"))
    assert (user.id, user.email) == ("abc", "a@b.c")
    for bad in [None, "", "not-a-jwt", token(secret="wrong-secret-wrong-secret-wrong-secret!"),
                token(exp_in=-120), token(aud="anon")]:
        with pytest.raises(AuthError):
            await v.verify(bad)


async def test_expired_token_says_so(auth_settings):
    with pytest.raises(AuthError, match="expired"):
        await TokenVerifier(auth_settings).verify(token(exp_in=-120))


def test_api_requires_a_valid_token(auth_client):
    assert auth_client.get("/documents").status_code == 401
    junk = {"Authorization": "Bearer junk"}
    assert auth_client.get("/documents", headers=junk).status_code == 401
    assert auth_client.get("/documents", headers=auth()).json() == []
    assert auth_client.get("/billing/me", headers=auth()).json()["email"] == "u1@example.com"
    # Public endpoints stay public.
    assert auth_client.get("/health").status_code == 200
    assert auth_client.get("/billing/plans").status_code == 200


def test_users_cannot_see_each_others_documents(auth_client):
    text = "Senior engineer. " * 30
    r = auth_client.post("/documents", data={"kind": "cv", "text": text}, headers=auth("alice"))
    doc_id = r.json()["id"]
    assert auth_client.get(f"/documents/{doc_id}", headers=auth("bob")).status_code == 404
    assert auth_client.delete(f"/documents/{doc_id}", headers=auth("bob")).status_code == 404
    assert auth_client.get("/documents", headers=auth("bob")).json() == []
    assert len(auth_client.get("/documents", headers=auth("alice")).json()) == 1


def test_websocket_needs_auth_message_first(auth_client):
    with auth_client.websocket_connect("/ws/session") as ws:
        ws.send_text(json.dumps({"type": "start"}))
        event = ws.receive_json()
    assert event["code"] == "auth"

    with auth_client.websocket_connect("/ws/session") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": "junk"}))
        assert ws.receive_json()["code"] == "auth"

    with auth_client.websocket_connect("/ws/session") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token()}))
        assert ws.receive_json() == {"type": "ready"}


def test_production_refuses_to_run_without_sign_in():
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import create_app

    s = Settings(_env_file=None, environment="production", llm_provider="fake",
                 stt_provider="fake", embedding_provider="fake", billing_provider="fake")
    with pytest.raises(RuntimeError, match="Fake billing"):
        app = create_app(s)
        app.dependency_overrides[get_settings] = lambda: s
        with TestClient(app):
            pass

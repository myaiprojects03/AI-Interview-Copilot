def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_provider_status_has_no_secrets(client):
    r = client.get("/health/providers")
    assert r.status_code == 200
    body = r.json()
    assert body["llm"] == {"provider": "fake", "model": None, "configured": True}
    assert body["database"]["configured"] is False

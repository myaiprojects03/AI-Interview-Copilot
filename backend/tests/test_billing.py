import hashlib
import hmac
import json
import time
from dataclasses import replace
from datetime import timedelta

import httpx
import respx

from app.billing.plans import month_key
from app.billing.provider import PaddleBilling, parse_paddle_subscription
from tests.phase3_utils import auth


def me(client, user="user-1") -> dict:
    return client.get("/billing/me", headers=auth(user)).json()


def test_plans_listing(auth_client):
    data = auth_client.get("/billing/plans").json()
    assert data["provider"] == "fake"
    assert [(p["id"], p["minutes"], p["price_usd_month"]) for p in data["plans"]] == [
        ("free", 30, 0), ("starter", 120, 9), ("pro", 600, 19),
    ]
    assert all(p["available"] for p in data["plans"])


def test_subscribe_upgrade_cancel_resume_with_fake_billing(auth_client):
    h = auth()
    assert me(auth_client)["plan"] == "free"
    assert me(auth_client)["usage"]["limit_minutes"] == 30

    r = auth_client.post("/billing/checkout", json={"plan": "starter"}, headers=h)
    assert r.json()["done"] is True
    account = me(auth_client)
    assert (account["plan"], account["status"], account["usage"]["limit_minutes"]) == (
        "starter", "active", 120)
    assert auth_client.post("/billing/checkout", json={"plan": "pro"}, headers=h).status_code == 409

    r = auth_client.post("/billing/change-plan", json={"plan": "pro"}, headers=h)
    assert r.json()["plan"] == "pro" and r.json()["usage"]["limit_minutes"] == 600
    assert auth_client.post("/billing/change-plan", json={"plan": "pro"},
                            headers=h).status_code == 409

    r = auth_client.post("/billing/cancel", headers=h)
    assert r.json()["cancel_at_period_end"] is True
    assert r.json()["plan"] == "pro"  # keeps access until the period ends

    r = auth_client.post("/billing/resume", headers=h)
    assert r.json()["cancel_at_period_end"] is False

    # Cancel, then let the billing period end at the provider.
    auth_client.post("/billing/cancel", headers=h)
    accounts = auth_client.app.state.accounts
    stored = accounts._subs["user-1"]
    auth_client.app.state.billing.end_period(stored.subscription_id)
    # Pretend our copy is stale so the dashboard refresh asks the provider again.
    accounts._subs["user-1"] = replace(stored, updated_at=stored.updated_at - timedelta(hours=1))
    account = me(auth_client)
    assert (account["plan"], account["status"]) == ("free", "canceled")
    assert account["usage"]["limit_minutes"] == 30


def test_actions_without_a_plan_are_refused(auth_client):
    def post(path, **kw):
        return auth_client.post(path, headers=auth(), **kw).status_code

    assert post("/billing/change-plan", json={"plan": "pro"}) == 409
    assert post("/billing/cancel") == 409
    assert post("/billing/resume") == 409
    assert post("/billing/portal") == 409
    assert post("/billing/checkout", json={"plan": "free"}) == 422


async def test_usage_counts_toward_the_plan_limit(auth_client):
    accounts = auth_client.app.state.accounts
    await accounts.add_usage("user-1", month_key(), 25 * 60)
    usage = me(auth_client)["usage"]
    assert (usage["used_minutes"], usage["remaining_minutes"]) == (25.0, 5.0)


# ---- Paddle ------------------------------------------------------------------------------

PADDLE_SUB = {
    "id": "sub_01", "status": "active", "customer_id": "ctm_01",
    "items": [{"price": {"id": "pri_pro"}}],
    "current_billing_period": {"ends_at": "2026-12-10T00:00:00Z"},
    "scheduled_change": {"action": "cancel", "effective_at": "2026-12-10T00:00:00Z"},
    "custom_data": {"user_id": "user-1"},
}


def test_parse_paddle_subscription():
    sub = parse_paddle_subscription(PADDLE_SUB)
    assert (sub.id, sub.price_id, sub.cancel_at_period_end, sub.user_id) == (
        "sub_01", "pri_pro", True, "user-1")
    assert sub.current_period_end.year == 2026


def sign(secret: str, body: bytes, ts: int | None = None) -> str:
    ts = ts or int(time.time())
    h1 = hmac.new(secret.encode(), f"{ts}:".encode() + body, hashlib.sha256).hexdigest()
    return f"ts={ts};h1={h1}"


def test_paddle_webhook_signature():
    p = PaddleBilling("key", "sandbox", "whsec")
    body = b'{"event_type":"subscription.updated"}'
    assert p.verify_webhook(body, sign("whsec", body))
    assert not p.verify_webhook(body, sign("other", body))
    assert not p.verify_webhook(body + b" ", sign("whsec", body))
    assert not p.verify_webhook(body, sign("whsec", body, ts=int(time.time()) - 3600))
    assert not p.verify_webhook(body, None)
    assert not PaddleBilling("key", "sandbox", None).verify_webhook(body, sign("whsec", body))


@respx.mock
async def test_paddle_api_calls():
    base = "https://sandbox-api.paddle.com"
    respx.get(f"{base}/transactions/txn_1").mock(return_value=httpx.Response(200, json={
        "data": {"id": "txn_1", "subscription_id": "sub_01", "custom_data": {"user_id": "u9"}}}))
    respx.get(f"{base}/subscriptions/sub_01").mock(return_value=httpx.Response(
        200, json={"data": {**PADDLE_SUB, "custom_data": None}}))
    change = respx.patch(f"{base}/subscriptions/sub_01").mock(
        return_value=httpx.Response(200, json={"data": PADDLE_SUB}))
    respx.post(f"{base}/subscriptions/sub_01/cancel").mock(
        return_value=httpx.Response(200, json={"data": PADDLE_SUB}))
    respx.post(f"{base}/customers/ctm_01/portal-sessions").mock(return_value=httpx.Response(
        201, json={"data": {"urls": {"general": {"overview": "https://portal/x"}}}}))
    respx.get(f"{base}/subscriptions/bad").mock(return_value=httpx.Response(
        404, json={"error": {"detail": "not found"}}))

    p = PaddleBilling("key", "sandbox")
    sub = await p.subscription_from_transaction("txn_1")
    assert sub.user_id == "u9"  # taken from the transaction when the subscription has none
    await p.change_plan("sub_01", "pri_starter")
    sent = json.loads(change.calls[0].request.content)
    assert sent["items"] == [{"price_id": "pri_starter", "quantity": 1}]
    assert (await p.cancel("sub_01")).cancel_at_period_end
    assert await p.portal_url("ctm_01", "sub_01") == "https://portal/x"
    try:
        await p.get_subscription("bad")
    except Exception as exc:  # noqa: BLE001
        assert "404" in str(exc) and "not found" in str(exc)
    else:
        raise AssertionError("expected BillingError")

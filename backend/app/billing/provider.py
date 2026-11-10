"""Billing provider interface, with Paddle Billing and a fake for dev / tests."""

import hashlib
import hmac
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import httpx


class BillingError(Exception):
    """A billing call failed. The message is safe to show to the user."""


@dataclass(frozen=True)
class RemoteSubscription:
    id: str
    customer_id: str | None
    status: str
    price_id: str | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    user_id: str | None  # from custom_data set at checkout


class BillingProvider(ABC):
    name: str

    @abstractmethod
    async def get_subscription(self, subscription_id: str) -> RemoteSubscription: ...

    @abstractmethod
    async def subscription_from_transaction(self, transaction_id: str) -> RemoteSubscription: ...

    @abstractmethod
    async def change_plan(self, subscription_id: str, price_id: str) -> RemoteSubscription: ...

    @abstractmethod
    async def cancel(self, subscription_id: str) -> RemoteSubscription:
        """Cancel at the end of the current billing period."""

    @abstractmethod
    async def resume(self, subscription_id: str) -> RemoteSubscription:
        """Undo a scheduled cancellation."""

    @abstractmethod
    async def portal_url(self, customer_id: str, subscription_id: str | None) -> str: ...

    @abstractmethod
    def verify_webhook(self, raw_body: bytes, signature: str | None) -> bool: ...


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_paddle_subscription(data: dict) -> RemoteSubscription:
    items = data.get("items") or []
    price = (items[0].get("price") or {}).get("id") if items else None
    scheduled = data.get("scheduled_change") or {}
    period = data.get("current_billing_period") or {}
    custom = data.get("custom_data") or {}
    return RemoteSubscription(
        id=data["id"],
        customer_id=data.get("customer_id"),
        status=data.get("status", "none"),
        price_id=price,
        current_period_end=_ts(period.get("ends_at")),
        cancel_at_period_end=scheduled.get("action") == "cancel",
        user_id=custom.get("user_id") if isinstance(custom, dict) else None,
    )


class PaddleBilling(BillingProvider):
    """Paddle Billing API v1 (https://developer.paddle.com/api-reference)."""

    name = "paddle"
    URLS = {"sandbox": "https://sandbox-api.paddle.com", "production": "https://api.paddle.com"}
    WEBHOOK_TOLERANCE_S = 300

    def __init__(self, api_key: str, environment: str, webhook_secret: str | None = None):
        self._base = self.URLS[environment]
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._webhook_secret = webhook_secret

    async def _call(self, method: str, path: str, json: dict | None = None) -> dict:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.request(
                    method, self._base + path, headers=self._headers, json=json
                )
        except httpx.HTTPError as exc:
            raise BillingError("Couldn't reach the billing provider. Try again.") from exc
        if r.status_code >= 400:
            try:
                detail = r.json().get("error", {}).get("detail") or r.text[:200]
            except ValueError:
                detail = r.text[:200]
            raise BillingError(f"Billing provider error ({r.status_code}): {detail}")
        return r.json().get("data", {})

    async def get_subscription(self, subscription_id):
        data = await self._call("GET", f"/subscriptions/{subscription_id}")
        return parse_paddle_subscription(data)

    async def subscription_from_transaction(self, transaction_id):
        txn = await self._call("GET", f"/transactions/{transaction_id}")
        sub_id = txn.get("subscription_id")
        if not sub_id:
            raise BillingError("That payment didn't create a subscription yet. Try again shortly.")
        sub = await self.get_subscription(sub_id)
        if not sub.user_id:  # custom_data lives on the transaction for the first payment
            custom = txn.get("custom_data") or {}
            sub = replace(sub, user_id=custom.get("user_id"))
        return sub

    async def change_plan(self, subscription_id, price_id):
        data = await self._call(
            "PATCH",
            f"/subscriptions/{subscription_id}",
            {"items": [{"price_id": price_id, "quantity": 1}],
             "proration_billing_mode": "prorated_immediately"},
        )
        return parse_paddle_subscription(data)

    async def cancel(self, subscription_id):
        data = await self._call(
            "POST", f"/subscriptions/{subscription_id}/cancel",
            {"effective_from": "next_billing_period"},
        )
        return parse_paddle_subscription(data)

    async def resume(self, subscription_id):
        data = await self._call(
            "PATCH", f"/subscriptions/{subscription_id}", {"scheduled_change": None}
        )
        return parse_paddle_subscription(data)

    async def portal_url(self, customer_id, subscription_id):
        body = {"subscription_ids": [subscription_id]} if subscription_id else {}
        data = await self._call("POST", f"/customers/{customer_id}/portal-sessions", body)
        return data["urls"]["general"]["overview"]

    def verify_webhook(self, raw_body, signature):
        """Paddle-Signature: ts=<unix>;h1=<hex hmac-sha256 of "ts:body">"""
        if not self._webhook_secret or not signature:
            return False
        parts = dict(p.split("=", 1) for p in signature.split(";") if "=" in p)
        ts, h1 = parts.get("ts"), parts.get("h1")
        if not ts or not h1 or not ts.isdigit():
            return False
        if abs(time.time() - int(ts)) > self.WEBHOOK_TOLERANCE_S:
            return False
        expected = hmac.new(
            self._webhook_secret.encode(), f"{ts}:".encode() + raw_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, h1)


class FakeBilling(BillingProvider):
    """Instant, in-memory billing so subscribe / upgrade / cancel can be tried without a
    payment provider. Never use in production."""

    name = "fake"
    PERIOD = timedelta(days=30)

    def __init__(self) -> None:
        self._subs: dict[str, RemoteSubscription] = {}

    def subscribe(self, user_id: str, price_id: str) -> RemoteSubscription:
        sub = RemoteSubscription(
            id=f"fake_sub_{uuid.uuid4().hex[:12]}",
            customer_id=f"fake_cus_{user_id}",
            status="active",
            price_id=price_id,
            current_period_end=datetime.now(UTC) + self.PERIOD,
            cancel_at_period_end=False,
            user_id=user_id,
        )
        self._subs[sub.id] = sub
        return sub

    def end_period(self, subscription_id: str) -> RemoteSubscription:
        """Simulate the billing period ending (a scheduled cancel takes effect)."""
        sub = self._subs[subscription_id]
        status = "canceled" if sub.cancel_at_period_end else "active"
        sub = replace(sub, status=status, current_period_end=datetime.now(UTC) + self.PERIOD)
        self._subs[subscription_id] = sub
        return sub

    def _get(self, subscription_id: str) -> RemoteSubscription:
        if subscription_id not in self._subs:
            raise BillingError("Subscription not found.")
        return self._subs[subscription_id]

    async def get_subscription(self, subscription_id):
        return self._get(subscription_id)

    async def subscription_from_transaction(self, transaction_id):
        raise BillingError("Fake billing has no transactions.")

    async def change_plan(self, subscription_id, price_id):
        sub = replace(self._get(subscription_id), price_id=price_id)
        self._subs[subscription_id] = sub
        return sub

    async def cancel(self, subscription_id):
        sub = replace(self._get(subscription_id), cancel_at_period_end=True)
        self._subs[subscription_id] = sub
        return sub

    async def resume(self, subscription_id):
        sub = replace(self._get(subscription_id), cancel_at_period_end=False)
        self._subs[subscription_id] = sub
        return sub

    async def portal_url(self, customer_id, subscription_id):
        raise BillingError("The billing portal needs a real payment provider (Paddle).")

    def verify_webhook(self, raw_body, signature):
        return False

"""Plans, the user's subscription and usage, and billing actions."""

import json
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from starlette.requests import HTTPConnection

from app.accounts.store import AccountStore
from app.billing.plans import ACCESS_STATUSES, PAID, PLANS, price_id
from app.billing.provider import (
    BillingError,
    BillingProvider,
    FakeBilling,
    PaddleBilling,
    parse_paddle_subscription,
)
from app.billing.service import account_view, apply_remote, quota, refresh_if_stale
from app.core.config import Settings
from app.core.deps import CurrentUser, SettingsDep, get_accounts

log = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])


def make_billing(settings: Settings) -> BillingProvider:
    if settings.billing_provider == "paddle":
        if not settings.paddle_api_key:
            raise RuntimeError("BILLING_PROVIDER=paddle needs PADDLE_API_KEY")
        return PaddleBilling(
            settings.paddle_api_key.get_secret_value(),
            settings.paddle_environment,
            settings.paddle_webhook_secret.get_secret_value()
            if settings.paddle_webhook_secret
            else None,
        )
    if settings.environment == "production":
        raise RuntimeError("Fake billing can't run in production; set BILLING_PROVIDER=paddle")
    return FakeBilling()


def get_billing(conn: HTTPConnection, settings: SettingsDep) -> BillingProvider:
    billing = getattr(conn.app.state, "billing", None)
    if billing is None:
        billing = conn.app.state.billing = make_billing(settings)
    return billing


AccountsDep = Annotated[AccountStore, Depends(get_accounts)]
BillingDep = Annotated[BillingProvider, Depends(get_billing)]


def _fail(exc: BillingError, status: int = 502) -> HTTPException:
    return HTTPException(status_code=status, detail=str(exc))


@router.get("/plans")
async def plans(settings: SettingsDep, billing: BillingDep) -> dict:
    return {
        "provider": billing.name,
        "paddle": {"environment": settings.paddle_environment}
        if billing.name == "paddle"
        else None,
        "plans": [
            {
                "id": p.id,
                "name": p.name,
                "price_usd_month": p.price_usd_month,
                "minutes": p.minutes,
                "blurb": p.blurb,
                "price_id": price_id(settings, p.id),
                "available": p.id == "free" or bool(price_id(settings, p.id)),
            }
            for p in PLANS.values()
        ],
    }


async def _view(accounts: AccountStore, user_id: str) -> dict:
    sub = await accounts.get_subscription(user_id)
    return account_view(sub, await quota(accounts, user_id))


@router.get("/me")
async def me(
    user: CurrentUser, settings: SettingsDep, accounts: AccountsDep, billing: BillingDep
) -> dict:
    await refresh_if_stale(accounts, settings, billing, user.id)
    return {"email": user.email, **await _view(accounts, user.id)}


class PlanIn(BaseModel):
    plan: Literal["starter", "pro"]


async def _active(accounts: AccountStore, user_id: str):
    sub = await accounts.get_subscription(user_id)
    if sub and sub.subscription_id and sub.plan in PAID and sub.status in ACCESS_STATUSES:
        return sub
    return None


@router.post("/checkout")
async def checkout(
    body: PlanIn, user: CurrentUser, settings: SettingsDep, accounts: AccountsDep,
    billing: BillingDep,
) -> dict:
    """Fake billing subscribes at once. Paddle returns what the browser needs to open
    Paddle Checkout; the browser then calls /billing/sync with the transaction id."""
    if await _active(accounts, user.id):
        raise HTTPException(409, "You already have a plan. Change it from your dashboard.")
    price = price_id(settings, body.plan)
    if not price:
        raise HTTPException(503, f"The {body.plan} plan isn't set up yet.")
    if isinstance(billing, FakeBilling):
        remote = billing.subscribe(user.id, price)
        await apply_remote(accounts, settings, billing, remote, expected_user=user.id)
        return {"provider": "fake", "done": True, "account": await _view(accounts, user.id)}
    return {
        "provider": billing.name,
        "done": False,
        "price_id": price,
        "custom_data": {"user_id": user.id},
        "email": user.email,
        "success_url": f"{settings.app_url}/dashboard?checkout=done",
    }


class SyncIn(BaseModel):
    transaction_id: str


@router.post("/sync")
async def sync_after_checkout(
    body: SyncIn, user: CurrentUser, settings: SettingsDep, accounts: AccountsDep,
    billing: BillingDep,
) -> dict:
    try:
        remote = await billing.subscription_from_transaction(body.transaction_id)
        await apply_remote(accounts, settings, billing, remote, expected_user=user.id)
    except BillingError as exc:
        raise _fail(exc, 400) from exc
    return await _view(accounts, user.id)


@router.post("/change-plan")
async def change_plan(
    body: PlanIn, user: CurrentUser, settings: SettingsDep, accounts: AccountsDep,
    billing: BillingDep,
) -> dict:
    sub = await _active(accounts, user.id)
    if not sub:
        raise HTTPException(409, "You don't have a paid plan yet. Choose one on the pricing page.")
    if sub.plan == body.plan:
        raise HTTPException(409, f"You're already on {PLANS[body.plan].name}.")
    try:
        remote = await billing.change_plan(sub.subscription_id, price_id(settings, body.plan))
        await apply_remote(accounts, settings, billing, remote, expected_user=user.id)
    except BillingError as exc:
        raise _fail(exc) from exc
    return await _view(accounts, user.id)


@router.post("/cancel")
async def cancel(
    user: CurrentUser, settings: SettingsDep, accounts: AccountsDep, billing: BillingDep
) -> dict:
    sub = await _active(accounts, user.id)
    if not sub:
        raise HTTPException(409, "There's no paid plan to cancel.")
    try:
        remote = await billing.cancel(sub.subscription_id)
        await apply_remote(accounts, settings, billing, remote, expected_user=user.id)
    except BillingError as exc:
        raise _fail(exc) from exc
    return await _view(accounts, user.id)


@router.post("/resume")
async def resume(
    user: CurrentUser, settings: SettingsDep, accounts: AccountsDep, billing: BillingDep
) -> dict:
    sub = await _active(accounts, user.id)
    if not sub or not sub.cancel_at_period_end:
        raise HTTPException(409, "There's no scheduled cancellation to undo.")
    try:
        remote = await billing.resume(sub.subscription_id)
        await apply_remote(accounts, settings, billing, remote, expected_user=user.id)
    except BillingError as exc:
        raise _fail(exc) from exc
    return await _view(accounts, user.id)


@router.post("/portal")
async def portal(user: CurrentUser, accounts: AccountsDep, billing: BillingDep) -> dict:
    sub = await accounts.get_subscription(user.id)
    if not sub or not sub.customer_id:
        raise HTTPException(409, "There's no billing account yet.")
    try:
        return {"url": await billing.portal_url(sub.customer_id, sub.subscription_id)}
    except BillingError as exc:
        raise _fail(exc, 400) from exc


@router.post("/webhook", include_in_schema=False)
async def webhook(
    request: Request, settings: SettingsDep, accounts: AccountsDep, billing: BillingDep
) -> dict:
    raw = await request.body()
    if not billing.verify_webhook(raw, request.headers.get("paddle-signature")):
        raise HTTPException(401, "Invalid signature.")
    event = json.loads(raw)
    kind = event.get("event_type", "")
    data = event.get("data") or {}
    try:
        if kind.startswith("subscription."):
            await apply_remote(accounts, settings, billing, parse_paddle_subscription(data))
        elif kind == "transaction.completed" and data.get("subscription_id"):
            remote = await billing.subscription_from_transaction(data["id"])
            await apply_remote(accounts, settings, billing, remote)
    except BillingError as exc:
        log.error("webhook %s failed: %s", kind, exc)
        raise HTTPException(500, "Couldn't process the event; it will be retried.") from exc
    return {"ok": True}

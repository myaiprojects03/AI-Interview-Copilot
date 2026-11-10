"""Keep each user's plan in step with the billing provider.

The provider is the source of truth. Its state reaches us three ways, all through
`apply_remote`: webhooks (production), an explicit sync right after checkout (works on
localhost, where webhooks can't reach), and a periodic refresh when the dashboard loads.
"""

import logging
from datetime import UTC, datetime, timedelta

from app.accounts.store import AccountStore, Subscription
from app.billing.plans import PLANS, effective_plan, month_key, plan_for_price
from app.billing.provider import BillingError, BillingProvider, RemoteSubscription
from app.core.config import Settings

log = logging.getLogger(__name__)

REFRESH_AFTER = timedelta(minutes=5)


async def apply_remote(
    accounts: AccountStore,
    settings: Settings,
    provider: BillingProvider,
    remote: RemoteSubscription,
    *,
    expected_user: str | None = None,
) -> Subscription | None:
    user_id = remote.user_id or (
        await accounts.user_for_customer(remote.customer_id) if remote.customer_id else None
    )
    if expected_user and user_id and user_id != expected_user:
        raise BillingError("That subscription belongs to a different account.")
    user_id = user_id or expected_user
    if not user_id:
        log.warning("subscription %s has no known user; ignoring", remote.id)
        return None
    plan = plan_for_price(settings, remote.price_id)
    if plan is None:
        log.warning("subscription %s has unknown price %s", remote.id, remote.price_id)
        plan = "free"
    sub = Subscription(
        user_id=user_id,
        plan=plan,
        status=remote.status,
        provider=provider.name,
        customer_id=remote.customer_id,
        subscription_id=remote.id,
        current_period_end=remote.current_period_end,
        cancel_at_period_end=remote.cancel_at_period_end,
    )
    await accounts.upsert_subscription(sub)
    return sub


async def refresh_if_stale(
    accounts: AccountStore, settings: Settings, provider: BillingProvider, user_id: str
) -> Subscription | None:
    sub = await accounts.get_subscription(user_id)
    if (
        sub
        and sub.subscription_id
        and sub.provider == provider.name
        and datetime.now(UTC) - sub.updated_at > REFRESH_AFTER
    ):
        try:
            remote = await provider.get_subscription(sub.subscription_id)
            sub = await apply_remote(accounts, settings, provider, remote, expected_user=user_id)
        except BillingError as exc:
            log.warning("refresh failed for %s: %s", user_id, exc)
    return sub


async def quota(accounts: AccountStore, user_id: str) -> dict:
    sub = await accounts.get_subscription(user_id)
    plan = effective_plan(sub)
    month = month_key()
    used = await accounts.usage_seconds(user_id, month)
    limit = plan.minutes * 60
    return {
        "plan": plan.id,
        "month": month,
        "used_seconds": used,
        "limit_seconds": limit,
        "remaining_seconds": max(0.0, limit - used),
    }


def account_view(sub: Subscription | None, usage: dict) -> dict:
    plan = PLANS[usage["plan"]]
    return {
        "plan": plan.id,
        "plan_name": plan.name,
        "subscribed_plan": sub.plan if sub else "free",
        "status": sub.status if sub else "none",
        "provider": sub.provider if sub else None,
        "cancel_at_period_end": bool(sub and sub.cancel_at_period_end),
        "current_period_end": sub.current_period_end if sub else None,
        "can_manage": bool(sub and sub.customer_id and sub.provider == "paddle"),
        "usage": {
            "month": usage["month"],
            "used_minutes": round(usage["used_seconds"] / 60, 1),
            "limit_minutes": plan.minutes,
            "remaining_minutes": round(usage["remaining_seconds"] / 60, 1),
        },
    }

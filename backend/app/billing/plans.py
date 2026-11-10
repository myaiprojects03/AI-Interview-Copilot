"""Plans and usage limits. Change prices and minutes here (and the matching prices in
Paddle, created by scripts/paddle_setup.py)."""

from dataclasses import dataclass
from datetime import UTC, datetime

from app.accounts.store import Subscription
from app.core.config import Settings


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    price_usd_month: int
    minutes: int  # live interview minutes per calendar month
    blurb: str


PLANS: dict[str, Plan] = {
    "free": Plan("free", "Free", 0, 30, "Try it on a mock interview."),
    "starter": Plan("starter", "Starter", 9, 120, "A few real interviews a month."),
    "pro": Plan("pro", "Pro", 19, 600, "For an active job search."),
}
PAID = ("starter", "pro")
# Statuses that still give access to the paid plan. past_due keeps access while the
# provider retries the payment; Paddle moves it to canceled if retries fail.
ACCESS_STATUSES = {"active", "trialing", "past_due"}


def price_id(settings: Settings, plan: str) -> str | None:
    if plan not in PAID:
        return None
    if settings.billing_provider == "fake":
        return f"fake_price_{plan}"
    return {"starter": settings.paddle_price_starter, "pro": settings.paddle_price_pro}[plan]


def plan_for_price(settings: Settings, price: str | None) -> str | None:
    for plan in PAID:
        if price and price_id(settings, plan) == price:
            return plan
    return None


def effective_plan(sub: Subscription | None) -> Plan:
    if sub and sub.plan in PAID and sub.status in ACCESS_STATUSES:
        return PLANS[sub.plan]
    return PLANS["free"]


def month_key(at: datetime | None = None) -> str:
    """Usage resets on the 1st of each month (UTC) for every plan."""
    return (at or datetime.now(UTC)).strftime("%Y-%m")

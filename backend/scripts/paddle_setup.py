"""Create the Starter and Pro plans in Paddle (sandbox by default) and print the price ids.

Safe to re-run: products and prices are matched by custom_data.plan and reused.

Run from backend/ after setting PADDLE_API_KEY in .env:
    python -m scripts.paddle_setup
Then copy the printed PADDLE_PRICE_* lines into backend/.env and set BILLING_PROVIDER=paddle.
"""

import asyncio
import sys

import httpx

from app.billing.plans import PAID, PLANS
from app.billing.provider import PaddleBilling
from app.core.config import get_settings


async def main() -> int:
    s = get_settings()
    if not s.paddle_api_key:
        print("Set PADDLE_API_KEY in backend/.env first.")
        return 1
    base = PaddleBilling.URLS[s.paddle_environment]
    headers = {"Authorization": f"Bearer {s.paddle_api_key.get_secret_value()}"}
    async with httpx.AsyncClient(base_url=base, headers=headers, timeout=20) as api:

        async def call(method: str, path: str, **kw) -> dict:
            r = await api.request(method, path, **kw)
            if r.status_code >= 400:
                raise SystemExit(f"Paddle {method} {path} failed ({r.status_code}): {r.text[:300]}")
            return r.json()

        products = (await call("GET", "/products", params={"per_page": 200}))["data"]
        prices = (await call("GET", "/prices", params={"per_page": 200}))["data"]
        print(f"Paddle {s.paddle_environment}\n")
        for plan_id in PAID:
            plan = PLANS[plan_id]
            product = next(
                (p for p in products if (p.get("custom_data") or {}).get("plan") == plan_id
                 and p.get("status") == "active"),
                None,
            )
            if not product:
                product = (await call("POST", "/products", json={
                    "name": f"AI Interview Copilot {plan.name}",
                    "tax_category": "standard",
                    "description": f"{plan.minutes} live interview minutes per month.",
                    "custom_data": {"plan": plan_id},
                }))["data"]
                print(f"created product {product['id']} ({plan.name})")
            amount = str(plan.price_usd_month * 100)
            price = next(
                (p for p in prices if p.get("product_id") == product["id"]
                 and p.get("status") == "active"
                 and p.get("unit_price", {}).get("amount") == amount
                 and (p.get("billing_cycle") or {}).get("interval") == "month"),
                None,
            )
            if not price:
                price = (await call("POST", "/prices", json={
                    "product_id": product["id"],
                    "description": f"{plan.name} monthly",
                    "unit_price": {"amount": amount, "currency_code": "USD"},
                    "billing_cycle": {"interval": "month", "frequency": 1},
                    "custom_data": {"plan": plan_id},
                }))["data"]
                print(f"created price {price['id']} (${plan.price_usd_month}/month)")
            print(f"PADDLE_PRICE_{plan_id.upper()}={price['id']}")
    print("\nCopy those two lines into backend/.env, and set BILLING_PROVIDER=paddle.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

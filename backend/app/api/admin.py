"""Admin latency view: per-turn timings across all users. Timings and question types only,
never what anyone said. Access is limited to ADMIN_EMAILS (and the dev user locally)."""

import statistics
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.accounts.store import AccountStore
from app.core.deps import CurrentUser, SettingsDep, get_accounts

router = APIRouter(prefix="/admin", tags=["admin"])
AccountsDep = Annotated[AccountStore, Depends(get_accounts)]

# (key in the stored timings, label shown in the admin view)
METRICS = [
    ("speech_end_to_first_token_ms", "Question end → first words on screen"),
    ("stt_ms", "Speech-to-text (final)"),
    ("retrieval_ms", "CV / JD retrieval"),
    ("llm_first_token_ms", "AI first token"),
    ("llm_total_ms", "AI full answer"),
]


def _require_admin(user, settings) -> None:
    local_dev = not settings.auth_enabled and settings.environment in ("development", "test")
    if local_dev:
        return
    if not user.email or user.email.lower() not in settings.admin_email_set:
        raise HTTPException(403, "Admins only.")


def _percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    k = (len(ordered) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def _summary(values: list[float]) -> dict | None:
    if not values:
        return None
    return {
        "count": len(values),
        "p50": round(statistics.median(values)),
        "p90": round(_percentile(values, 0.90)),
        "p95": round(_percentile(values, 0.95)),
        "max": round(max(values)),
    }


@router.get("/latency")
async def latency(
    user: CurrentUser,
    settings: SettingsDep,
    accounts: AccountsDep,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> dict:
    _require_admin(user, settings)
    since = datetime.now(UTC) - timedelta(days=days)
    rows = await accounts.answer_timings(since)

    metrics = []
    for key, label in METRICS:
        values = [
            float(r.timings[key]) for r in rows if isinstance(r.timings.get(key), int | float)
        ]
        metrics.append({"key": key, "label": label, "summary": _summary(values)})

    by_day: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        value = r.timings.get("speech_end_to_first_token_ms")
        if isinstance(value, int | float):
            by_day[r.created_at.date().isoformat()].append(float(value))

    statuses: dict[str, int] = defaultdict(int)
    for r in rows:
        statuses[r.status] += 1

    recent = [
        {
            "at": r.created_at,
            "question_type": r.question_type,
            "status": r.status,
            **{k: r.timings.get(k) for k, _ in METRICS},
        }
        for r in sorted(rows, key=lambda r: r.created_at, reverse=True)[:25]
    ]
    return {
        "days": days,
        "answers": len(rows),
        "statuses": dict(statuses),
        "metrics": metrics,
        "daily": [
            {"day": day, **(_summary(v) or {})} for day, v in sorted(by_day.items())
        ],
        "recent": recent,
    }

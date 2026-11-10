"""Retry policy for AI provider calls.

One retry on rate limits (429), server errors (5xx) and network failures, waiting what the
provider asks for (Retry-After), capped so a live interview never stalls for long.
"""

import httpx

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_WAIT_S = 4.0
DEFAULT_WAIT_S = 1.0
ATTEMPTS = 2


def wait_seconds(response: httpx.Response | None) -> float:
    if response is not None:
        value = response.headers.get("retry-after", "")
        try:
            return min(MAX_WAIT_S, max(0.0, float(value)))
        except ValueError:
            pass
    return DEFAULT_WAIT_S


def error_message(service: str, status: int, body: str) -> str:
    if status == 429:
        return (
            f"{service} is busy right now (free-tier rate limit). "
            "Wait a few seconds and try again."
        )
    if status in (401, 403):
        return f"{service} rejected the API key (HTTP {status}). Check the key in backend/.env."
    return f"{service} returned HTTP {status}: {body[:300]}"

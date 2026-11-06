"""Flag figures in an answer that don't come from the CV.

The model sometimes invents metrics ("cut costs by 30%") even when told not to. Rather than
let the candidate say an invented number in an interview, the UI highlights any figure here
so they can check it. Plain numbers like "HTTP 429" or "100 req/min" aren't flagged; only
figures that read like a claim: percentages, durations, money, multipliers and years.
"""

import re

_NUMBER = r"\d+(?:[.,]\d+)?"
_FIGURE = re.compile(
    rf"""
    (?:[$£€]\s?{_NUMBER}\s?(?:k|m|bn|million|billion)?)          # money
    | (?:\b{_NUMBER}\s?(?:%|percent\b))                          # percentages
    | (?:\b{_NUMBER}\s?(?:x\b|times\b))                          # multipliers
    | (?:\b{_NUMBER}\s?(?:ms|milliseconds?|seconds?|minutes?|hours?|days?|weeks?|months?|years?)\b)
    | (?:\b(?:19|20)\d{{2}}\b)                                   # years
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _squash(text: str) -> str:
    """Lower-case, "percent" -> "%", no spaces or thousands commas, singular units."""
    t = text.lower().replace("percent", "%")
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)
    t = re.sub(r"\s+", "", t)
    return re.sub(r"(second|minute|hour|day|week|month|year|millisecond)s\b", r"\1", t)


def unverified_figures(answer: str, cv_text: str) -> list[str]:
    """Figures in `answer` (number together with its unit) that the CV never states."""
    cv = _squash(cv_text)
    found: list[str] = []
    for match in _FIGURE.finditer(answer):
        figure = match.group(0).strip()
        stated = re.search(r"(?<![\d.])" + re.escape(_squash(figure)), cv)
        if not stated and figure not in found:
            found.append(figure)
    return found

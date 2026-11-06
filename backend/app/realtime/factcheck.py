"""Flag figures in an answer that don't come from the CV.

The model sometimes invents metrics ("cut costs by 30%", "within a three-month sprint")
even when told not to. Rather than let the candidate say an invented number in an
interview, the UI highlights any such figure so they can check it. Plain numbers like
"HTTP 429" or "100 req/min" aren't flagged; only figures that read like a claim:
percentages, durations, money, multipliers and years, written in digits or words.
"""

import re

_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "ninety": 90, "hundred": 100,
}
_WORD = r"(?:" + "|".join(_WORDS) + r")"
_NUMBER = rf"(?:\d+(?:[.,]\d+)?|{_WORD})"
_SEP = r"[\s\-‐‑]?"  # space, hyphen or the non-breaking hyphens models like to use
_UNITS = r"(?:ms|milliseconds?|seconds?|minutes?|hours?|days?|weeks?|months?|years?)"
_FIGURE = re.compile(
    rf"""
    (?:[$£€]\s?\d+(?:[.,]\d+)?\s?(?:k|m|bn|million|billion)?)    # money
    | (?:\b{_NUMBER}{_SEP}(?:%|percent\b))                        # percentages
    | (?:\b{_NUMBER}{_SEP}(?:x\b|times\b|fold\b))                 # multipliers
    | (?:\b{_NUMBER}{_SEP}{_UNITS}\b)                             # durations
    | (?:\b(?:19|20)\d{{2}}\b)                                    # years
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _squash(text: str) -> str:
    """Comparable form: lower-case, number words as digits, "percent" -> "%", no spaces,
    hyphens or thousands commas, singular units."""
    t = text.lower().replace("percent", "%")
    t = re.sub(rf"\b{_WORD}\b", lambda m: str(_WORDS[m.group(0)]), t)
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)
    t = re.sub(r"[\s\-‐‑]+", "", t)
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

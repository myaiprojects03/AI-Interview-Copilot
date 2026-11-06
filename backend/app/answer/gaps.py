"""Skills the job asks for that the CV doesn't show ("gaps").

Two uses:
1. The prompt lists them explicitly ("the candidate does NOT have: AWS, Go, ..."). A concrete
   list stops the model claiming them far better than a general rule does.
2. Answers are scanned for them, and the UI highlights any mention so the candidate doesn't
   claim a skill they don't have.

The LLM proposes the list once per CV + job description pair; every item is then checked
against the CV text so a skill the CV does mention never ends up on it.
"""

import json
import logging
import re
from dataclasses import dataclass

from app.providers.base import ChatMessage, LLMProvider, ProviderError

log = logging.getLogger(__name__)

MAX_GAPS = 15

_PROMPT = """Compare a job description with a candidate's CV.
List what the JOB asks for that the CV shows NO evidence of. Go through the job line by \
line and check both kinds of item:
1. Skills, tools, technologies, programming languages, platforms, certifications.
2. Duties and activities, e.g. "mentor engineers", "lead design reviews", "run on-call", \
"write post-mortems", "manage a team". A duty counts as a gap unless the CV shows the \
candidate actually doing it.

Rules:
- Only items the job description explicitly mentions.
- Leave out anything the CV shows, even under another name ("Postgres" = "PostgreSQL").
- Short names, 1 to 3 words.
- For each item give "aliases": the exact words to search for in text (include plurals and \
verb forms, e.g. "mentor", "mentoring", "mentored").
- At most 15 items, most important first.

Reply with JSON only:
{"gaps": [{"skill": "AWS", "aliases": ["AWS", "Amazon Web Services"]}, \
{"skill": "Mentoring", "aliases": ["mentor", "mentoring", "mentored"]}]}"""


@dataclass(frozen=True)
class SkillGap:
    skill: str
    aliases: tuple[str, ...]


def _alias_pattern(alias: str) -> re.Pattern:
    """Short or all-caps aliases ("Go", "AWS") match case-sensitively and as whole words, so
    the verb "go" isn't mistaken for the language. Longer ones also match word endings
    ("mentor" -> "mentoring")."""
    escaped = re.escape(alias).replace(r"\ ", r"[\s\-]+")
    if len(alias) <= 3 or alias.isupper():
        return re.compile(rf"(?<![\w-]){escaped}(?![\w])")
    suffix = r"\w*" if len(alias) >= 5 else ""
    return re.compile(rf"(?<![\w-]){escaped}{suffix}", re.IGNORECASE)


def mentions(text: str, gap: SkillGap) -> list[str]:
    found: list[str] = []
    for alias in gap.aliases:
        for m in _alias_pattern(alias).finditer(text):
            if m.group(0) not in found:
                found.append(m.group(0))
    return found


def mentioned_gaps(answer: str, gaps: list[SkillGap], question: str = "") -> list[dict]:
    """[{"skill": "AWS", "matches": ["AWS"]}] for every gap the answer mentions.

    Skills the question itself names ("How would you design a rate limiter?") are skipped:
    talking about them is answering, not claiming experience."""
    out = []
    for gap in gaps:
        if question and mentions(question, gap):
            continue
        matches = mentions(answer, gap)
        if matches:
            out.append({"skill": gap.skill, "matches": matches})
    return out


def _specific(alias: str, skill: str) -> bool:
    """For a multi-word skill ("Design reviews") a lone word ("review") is too generic to
    search for; keep only aliases that are phrases, hyphenated or acronyms."""
    if len(skill.split()) < 2:
        return True
    return len(alias.split()) >= 2 or "-" in alias or alias.isupper()


def _parse(raw: str) -> list[SkillGap]:
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    gaps: list[SkillGap] = []
    for item in data.get("gaps", []) if isinstance(data, dict) else []:
        if not isinstance(item, dict) or not isinstance(item.get("skill"), str):
            continue
        skill = item["skill"].strip()[:40]
        aliases = [a.strip() for a in item.get("aliases", []) if isinstance(a, str)]
        aliases = [
            a for a in dict.fromkeys([skill, *aliases]) if 2 <= len(a) <= 40 and _specific(a, skill)
        ]
        if skill and aliases:
            gaps.append(SkillGap(skill, tuple(aliases)))
    return gaps


def verify(gaps: list[SkillGap], cv_text: str) -> list[SkillGap]:
    """Drop any "gap" the CV actually mentions, and duplicates."""
    out: list[SkillGap] = []
    seen: set[str] = set()
    for gap in gaps:
        if gap.skill.lower() in seen or mentions(cv_text, gap):
            continue
        seen.add(gap.skill.lower())
        out.append(gap)
    return out[:MAX_GAPS]


_cache: dict[tuple[str, str], list[SkillGap]] = {}


async def find_gaps(
    llm: LLMProvider, *, cv_text: str, jd_text: str, cache_key: tuple[str, str] | None = None
) -> list[SkillGap]:
    if cache_key and cache_key in _cache:
        return _cache[cache_key]
    messages = [
        ChatMessage("system", _PROMPT),
        ChatMessage("user", f"<cv>\n{cv_text[:12_000]}\n</cv>\n\n<job>\n{jd_text[:8_000]}\n</job>"),
    ]
    try:
        raw = await llm.complete(messages, max_tokens=1200, temperature=0.0)
    except ProviderError as exc:
        log.warning("gap analysis failed: %s", exc)
        return []
    gaps = verify(_parse(raw), cv_text)
    if cache_key:
        if len(_cache) > 256:
            _cache.clear()
        _cache[cache_key] = gaps
    return gaps

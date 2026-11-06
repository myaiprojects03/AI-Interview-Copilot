"""Split CV / job-description text into small, self-contained chunks for retrieval.

Each chunk carries its context: the section ("Experience") and, inside experience, the role
header ("Senior Backend Engineer, Brightlane Payments (2022 to present)"). A bullet like
"Cut p99 latency from 480 ms to 120 ms" is useless without knowing where it happened.
"""

import re
from dataclasses import dataclass

MAX_WORDS = 90
MIN_WORDS = 35

_YEAR = re.compile(r"\b(19|20)\d{2}\b|\bpresent\b|\bcurrent\b|\bnow\b", re.IGNORECASE)


@dataclass(frozen=True)
class Chunk:
    text: str  # context prefix + body; what gets embedded and shown to the LLM
    section: str | None
    role: str | None


def _words(s: str) -> int:
    return len(s.split())


def _is_bullet(line: str) -> bool:
    return line.startswith("- ")


def _is_heading(line: str) -> bool:
    if line.startswith("#"):
        return True
    if _is_bullet(line) or _words(line) > 5 or line.endswith((".", ",", ";")):
        return False
    letters = [c for c in line if c.isalpha()]
    if not letters or sum(c.isdigit() for c in line) > 0:
        return False
    return line.isupper() or line.rstrip(":").istitle() or line.endswith(":")


def _is_role_header(line: str) -> bool:
    return not _is_bullet(line) and bool(_YEAR.search(line)) and _words(line) <= 25


def _clean_heading(line: str) -> str:
    return line.lstrip("#").strip().rstrip(":").strip("* ").strip()


def chunk_text(text: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    section: str | None = None
    role: str | None = None
    role_emitted = True
    body: list[str] = []

    def flush() -> None:
        nonlocal body, role_emitted
        content = "\n".join(body).strip()
        if not content and role and not role_emitted:
            content = ""  # a role/education line with no bullets still deserves a chunk
        elif not content:
            body = []
            return
        context = " · ".join(p for p in (section, role) if p)
        full = f"{context}\n{content}".strip() if context else content
        if full:
            chunks.append(Chunk(text=full, section=section, role=role))
            role_emitted = True
        body = []

    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            if _words("\n".join(body)) >= MIN_WORDS:
                flush()
            continue
        if _is_heading(line):
            flush()
            section = _clean_heading(line)
            role = None
            continue
        if _is_role_header(line):
            flush()
            role = line.strip("*_ ").replace("**", "")
            role_emitted = False
            continue
        if body and _words("\n".join(body)) + _words(line) > MAX_WORDS:
            flush()
        body.append(line.replace("**", ""))
    flush()
    return chunks

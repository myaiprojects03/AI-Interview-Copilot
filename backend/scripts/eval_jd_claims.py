"""Measure how often answers claim job-description skills the CV doesn't have.

Uses Sara's test CV (evals/sara_cv.md) and the Lumen Pay job (evals/sample_jd.md), where the
job asks for things Sara's CV lacks (AWS, Go, Python, Kafka, mentoring, design reviews,
on-call, post-mortems). Asks fit-style questions, the ones most tempted to over-claim, and
prints every mention with its sentence, marked CLAIM or ok (honest gap framing such as
"keen to learn AWS" or "your Go stack"). Review the CLAIM lines by eye: the marking is a
heuristic.

Run from backend/:
    python -m scripts.eval_jd_claims            # with the gap list (current behaviour)
    python -m scripts.eval_jd_claims --no-gaps  # without it, for comparison
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path

from app.answer.classify import classify
from app.answer.gaps import find_gaps
from app.answer.prompts import build_messages
from app.answer.retrieval import load_context, retrieve
from app.core.config import get_settings
from app.documents.service import ingest
from app.documents.store import MemoryStore
from app.providers.registry import get_embedder, get_llm

EVALS = Path(__file__).resolve().parents[1] / "evals"
QUESTIONS = [
    "Can you tell me a little about yourself?",
    "Why do you want to work here?",
    "What are your greatest strengths?",
    "Why should we hire you?",
    "What makes you a good fit for this role?",
    "How does your experience match our requirements?",
]
# Ground truth for this pair, independent of the gap finder.
JD_ONLY = re.compile(
    r"(?<![\w-])(AWS|Go|Golang|Python|Kafka|mentor\w*|design reviews?|on-?call|"
    r"post-?mortems?)(?![\w])",
)
FRAMING = re.compile(
    r"learn|grow|keen|eager|ramp|pick up|haven't|have not|not yet|new to|transferable|"
    r"\byour\b|you're|you need|you use|the role|this role|lumen",
    re.I,
)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-gaps", action="store_true")
    parser.add_argument("--reps", type=int, default=2)
    parser.add_argument("--pace", type=float, default=14.0)
    args = parser.parse_args()

    s = get_settings()
    llm, emb, store = get_llm(s), get_embedder(s), MemoryStore()
    cv_text = (EVALS / "sara_cv.md").read_text(encoding="utf-8")
    jd_text = (EVALS / "sample_jd.md").read_text(encoding="utf-8")
    cv = await ingest(user_id="e", kind="cv", text=cv_text, filename=None, title="Sara",
                      store=store, embedder=emb, llm=llm)
    jd = await ingest(user_id="e", kind="jd", text=jd_text, filename=None, title="Lumen",
                      store=store, embedder=emb, llm=llm)
    ctx = await load_context(store, "e", cv_id=cv.id, jd_id=jd.id, sample_cv_text="")
    if not args.no_gaps:
        await asyncio.sleep(args.pace)
        ctx.gaps = await find_gaps(llm, cv_text=cv.content, jd_text=jd.content)
        print("Gaps found:", ", ".join(g.skill for g in ctx.gaps) or "(none)")

    answers = claims = 0
    for q in QUESTIONS:
        for _ in range(args.reps):
            await asyncio.sleep(args.pace)
            kind = classify(q)
            excerpts = await retrieve(ctx, emb, q)
            out = await llm.complete(
                build_messages(q, kind=kind, context=ctx, excerpts=excerpts), max_tokens=700
            )
            answers += 1
            flat = " ".join(out.split())
            sentences = re.split(r"(?<=[.!?])\s+|\s-\s", flat)
            found = []
            for sentence in sentences:
                for m in JD_ONLY.finditer(sentence):
                    label = "ok   " if FRAMING.search(sentence) else "CLAIM"
                    found.append((label, m.group(0), sentence.strip()[:160]))
            has_claim = any(f[0] == "CLAIM" for f in found)
            claims += has_claim
            print(f"\n{'CLAIM' if has_claim else 'clean'} | {q}")
            for label, term, sentence in found:
                print(f"   {label} [{term}] {sentence}")

    print(f"\n==== {claims}/{answers} answers contain a likely false claim "
          f"({'without' if args.no_gaps else 'with'} gap list) ====")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

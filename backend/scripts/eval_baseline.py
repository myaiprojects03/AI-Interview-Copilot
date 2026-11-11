"""Before/after comparison: a plain chat prompt vs the copilot's answer pipeline.

Same 15 labelled questions, same sample CV and job description, same model. "Before" is
what a candidate gets from a general chat tool: the whole CV, the job and the question in
one prompt, read once the full answer is back. "After" is the copilot: classified question,
retrieved CV sections, and the answer streamed word by word.

Both answers are scored with the same checks as scripts/eval_answers.py:
- figures not in the CV or job description
- spoken length: within the word limit for the question type

Run from backend/ (paced for Groq's free tier, ~10 minutes):
    python -m scripts.eval_baseline
"""

import asyncio
import json
import re
import statistics
import sys
import time

from app.answer.classify import classify
from app.answer.prompts import _WORDS, SAMPLE_CV, build_messages
from app.answer.retrieval import load_context, retrieve
from app.core.config import get_settings
from app.documents.service import ingest
from app.documents.store import MemoryStore
from app.providers.base import ChatMessage, ProviderError
from app.providers.registry import get_embedder, get_llm
from app.realtime.factcheck import unverified_figures
from scripts.eval_answers import EVALS, pick

PACE = 15.0
PLAIN_SYSTEM = ("You are helping a job candidate during a live interview. Answer the "
                "interviewer's question as the candidate, using their CV and the job description.")


async def timed(llm, messages, max_tokens):
    """(first_token_ms, total_ms, text), retrying on rate limits."""
    for attempt in range(1, 6):
        t0, first, text = time.perf_counter(), None, ""
        try:
            async for delta in llm.stream_chat(messages, max_tokens=max_tokens):
                first = first or (time.perf_counter() - t0) * 1000
                text += delta
            return first, (time.perf_counter() - t0) * 1000, text
        except ProviderError:
            if attempt == 5:
                raise
            await asyncio.sleep(20 * attempt)  # free-tier rate limit: back off and retry


def words(text: str) -> int:
    return len(re.sub(r"```.*?(```|$)", "", text, flags=re.S).split())


async def main() -> int:
    settings = get_settings()
    llm, embedder = get_llm(settings), get_embedder(settings)
    store = MemoryStore()
    jd_text = (EVALS / "sample_jd.md").read_text(encoding="utf-8")
    cv = await ingest(user_id="eval", kind="cv", text=SAMPLE_CV, filename=None, title="Sample",
                      store=store, embedder=embedder, llm=llm)
    await asyncio.sleep(PACE)
    jd = await ingest(user_id="eval", kind="jd", text=jd_text, filename=None, title="Lumen Pay",
                      store=store, embedder=embedder, llm=llm)
    context = await load_context(store, "eval", cv_id=cv.id, jd_id=jd.id, sample_cv_text="")
    questions = pick(json.loads((EVALS / "questions.json").read_text(encoding="utf-8")), False)

    rows = []
    for i, item in enumerate(questions, 1):
        q = item["q"]
        kind = classify(q)
        facts = context.fact_text + "\n" + q
        limit = _WORDS[kind.type] * 1.15

        await asyncio.sleep(PACE)
        plain = [ChatMessage("system", PLAIN_SYSTEM),
                 ChatMessage("user", f"My CV:\n{SAMPLE_CV}\n\nThe job:\n{jd_text}\n\n"
                                     f"Interviewer's question: {q}")]
        _, b_total, b_text = await timed(llm, plain, 1500)

        await asyncio.sleep(PACE)
        excerpts = await retrieve(context, embedder, q)
        messages = build_messages(q, kind=kind, context=context, excerpts=excerpts)
        a_first, _, a_text = await timed(llm, messages, settings.answer_max_tokens)

        row = {
            "q": q,
            "before_wait_ms": b_total, "after_wait_ms": a_first,
            "before_figures": unverified_figures(b_text, facts),
            "after_figures": unverified_figures(a_text, facts),
            "before_words": words(b_text), "after_words": words(a_text),
            "before_in_limit": words(b_text) <= limit, "after_in_limit": words(a_text) <= limit,
        }
        rows.append(row)
        print(f"[{i:2}/{len(questions)}] wait {b_total:6.0f} -> {a_first:5.0f} ms | "
              f"words {row['before_words']:4} -> {row['after_words']:3} | "
              f"figures {len(row['before_figures'])} -> {len(row['after_figures'])} | {q}")

    n = len(rows)
    summary = {
        "questions": n,
        "wait_median_ms": [round(statistics.median(r[f"{s}_wait_ms"] for r in rows))
                           for s in ("before", "after")],
        "wait_max_ms": [round(max(r[f"{s}_wait_ms"] for r in rows)) for s in ("before", "after")],
        "answers_with_unsupported_figures": [sum(bool(r[f"{s}_figures"]) for r in rows)
                                             for s in ("before", "after")],
        "answers_within_spoken_length": [sum(r[f"{s}_in_limit"] for r in rows)
                                         for s in ("before", "after")],
        "words_median": [round(statistics.median(r[f"{s}_words"] for r in rows))
                         for s in ("before", "after")],
    }
    print("\n==== Before -> After ====")
    for k, v in summary.items():
        print(f"{k:36} {v}")
    (EVALS / "baseline_report.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

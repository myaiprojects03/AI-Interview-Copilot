"""Evaluate answer quality on the labelled question set (evals/questions.json).

Uses the real pipeline: sample CV + sample job description ingested with real embeddings and
summaries, classifier, retrieval, prompt and the configured LLM. For each answer it checks:

- format: STAR labels for behavioral questions only; a code block only when code was asked
- length: within the word limit for the question type (code blocks excluded)
- facts: no figures that aren't in the CV / job description
- speed: time to first token

Paced for Groq's free tier (8,000 tokens a minute), so expect ~15 s per question.

Run from backend/:
    python -m scripts.eval_answers              # 15 questions, 5 of each type
    python -m scripts.eval_answers --all        # every question
"""

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from pathlib import Path

from app.answer.classify import classify
from app.answer.prompts import _WORDS, SAMPLE_CV, build_messages
from app.answer.retrieval import load_context, retrieve
from app.core.config import get_settings
from app.documents.service import ingest
from app.documents.store import MemoryStore
from app.providers.base import ProviderError
from app.providers.registry import get_embedder, get_llm
from app.realtime.factcheck import unverified_figures

EVALS = Path(__file__).resolve().parents[1] / "evals"
STAR = re.compile(r"\*\*[STAR]:\*\*")


def check(answer: str, qtype: str, wants_code: bool, facts: str) -> dict:
    star_labels = len(STAR.findall(answer))
    has_code = "```" in answer
    prose = re.sub(r"```.*?(```|$)", "", answer, flags=re.S)
    words = len(prose.split())
    figures = unverified_figures(answer, facts)
    problems = []
    if qtype == "behavioral" and star_labels < 4:
        problems.append(f"only {star_labels}/4 STAR labels")
    if qtype != "behavioral" and star_labels:
        problems.append("STAR labels on a non-behavioral question")
    if wants_code and not has_code:
        problems.append("no code block")
    if not wants_code and has_code:
        problems.append("unrequested code")
    if words > _WORDS[qtype] * 1.15:
        problems.append(f"{words} words (limit {_WORDS[qtype]})")
    if figures:
        problems.append(f"invented figures {figures}")
    if not answer.strip():
        problems.append("empty answer")
    return {"words": words, "figures": figures, "problems": problems}


def pick(questions: list[dict], all_: bool) -> list[dict]:
    if all_:
        return questions
    out: list[dict] = []
    for t in ("behavioral", "technical", "general"):
        group = [q for q in questions if q["type"] == t]
        coded = [q for q in group if q.get("code")][:2]
        out += coded + [q for q in group if q not in coded][: 5 - len(coded)]
    return out


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--only", choices=["behavioral", "technical", "general"])
    parser.add_argument("--pace", type=float, default=15.0, help="seconds between LLM calls")
    args = parser.parse_args()

    settings = get_settings()
    llm, embedder = get_llm(settings), get_embedder(settings)
    store = MemoryStore()
    jd_text = (EVALS / "sample_jd.md").read_text(encoding="utf-8")
    print("Ingesting sample CV and job description ...")
    cv = await ingest(user_id="eval", kind="cv", text=SAMPLE_CV, filename=None, title="Sample",
                      store=store, embedder=embedder, llm=llm)
    await asyncio.sleep(args.pace)
    jd = await ingest(user_id="eval", kind="jd", text=jd_text, filename=None, title="Lumen Pay",
                      store=store, embedder=embedder, llm=llm)
    context = await load_context(store, "eval", cv_id=cv.id, jd_id=jd.id, sample_cv_text="")
    print(f"CV summary:\n{cv.summary}\n")

    questions = json.loads((EVALS / "questions.json").read_text(encoding="utf-8"))
    if args.only:
        questions = [q for q in questions if q["type"] == args.only]
    questions = pick(questions, args.all or bool(args.only))
    rows = []
    for i, item in enumerate(questions, 1):
        await asyncio.sleep(args.pace)
        kind = classify(item["q"])
        excerpts = await retrieve(context, embedder, item["q"])
        messages = build_messages(item["q"], kind=kind, context=context, excerpts=excerpts)
        for attempt in (1, 2):
            t0 = time.perf_counter()
            first = None
            answer = ""
            try:
                async for delta in llm.stream_chat(messages, max_tokens=settings.answer_max_tokens):
                    first = first or (time.perf_counter() - t0) * 1000
                    answer += delta
                break
            except ProviderError as exc:
                wait = re.search(r"try again in ([\d.]+)s", str(exc))
                if attempt == 2 or not wait:
                    answer = ""
                    print(f"  !! {exc}")
                    break
                await asyncio.sleep(float(wait.group(1)) + 1)
        result = check(answer, kind.type, kind.wants_code, context.fact_text + "\n" + item["q"])
        rows.append({**item, "got": kind.type, "first_ms": first, "answer": answer, **result})
        status = "OK " if not result["problems"] else "FIX"
        print(f"[{i:2}/{len(questions)}] {status} {kind.type:10} {first or 0:5.0f} ms  {item['q']}")
        for p in result["problems"]:
            print(f"        - {p}")

    ok = [r for r in rows if not r["problems"]]
    firsts = sorted(r["first_ms"] for r in rows if r["first_ms"])
    summary = {
        "answers": len(rows),
        "passed": len(ok),
        "classified_correctly": sum(r["got"] == r["type"] for r in rows),
        "with_invented_figures": sum(bool(r["figures"]) for r in rows),
        "first_token_median_ms": round(statistics.median(firsts)) if firsts else None,
        "first_token_max_ms": round(max(firsts)) if firsts else None,
    }
    print("\n==== Summary ====")
    for k, v in summary.items():
        print(f"{k:24} {v}")

    lines = [
        "# Answer evaluation",
        "",
        f"Model `{settings.groq_llm_model}`, reasoning effort `{settings.groq_reasoning_effort}`. "
        "Sample CV + sample job description. Generated by `python -m scripts.eval_answers`.",
        "",
        *(f"- **{k.replace('_', ' ')}**: {v}" for k, v in summary.items()),
        "",
    ]
    for r in rows:
        mark = "✅" if not r["problems"] else "⚠️ " + "; ".join(r["problems"])
        lines += [f"## {r['q']}", "", f"`{r['got']}` · first token {r['first_ms'] or 0:.0f} ms · "
                  f"{r['words']} words · {mark}", "", r["answer"].strip(), ""]
    (EVALS / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nFull answers written to {EVALS / 'report.md'}")
    return 0 if len(ok) == len(rows) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

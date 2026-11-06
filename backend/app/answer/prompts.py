"""Answer prompts: one template per question type, grounded in the candidate's CV and the
job description. Tuned with scripts/eval_answers.py against evals/questions.json."""

from pathlib import Path
from typing import Literal

from app.answer.classify import Classification
from app.answer.retrieval import InterviewContext, ScoredChunk
from app.providers.base import ChatMessage

SessionType = Literal["mixed", "behavioral", "technical"]

SAMPLE_CV = (Path(__file__).resolve().parent.parent / "data" / "sample_cv.md").read_text(
    encoding="utf-8"
)

_BASE = """You are a live interview copilot. The user is a job candidate in a live interview \
and glances at your text while talking. Write what the candidate can say: first person, \
natural spoken English.

{format}

Facts (strict):
- Ground the answer in the candidate's real roles, companies, projects and numbers from the \
CV material in the user message.
- Every number, date, percentage or duration you write must appear word for word in the CV \
material. Don't calculate new figures from it (no "75% faster" from "480 ms to 120 ms"); \
quote the CV's own numbers. If a point needs a number the CV doesn't have, write \
"[your number]" instead of inventing one.
- Never invent employers, job titles, incidents, deadlines, timeframes or outcomes. Tell \
the story with only what the CV says; general wording ("under a tight deadline") is fine, \
made-up specifics are not. If the CV has nothing relevant, answer well without pretending \
it happened.
- The job description lists what the employer wants, NOT what the candidate has done. Never \
claim a skill, tool, platform or activity from it (e.g. mentoring, a cloud provider, a \
language) unless the CV states it too. Use it only to choose which CV facts to stress and to \
say why they matter for this role; for gaps, say you're keen to grow into them.
- At most {words} words. No heading, no preamble, no closing remarks."""

_FORMATS = {
    "behavioral": """The question asks for a real past experience. Tell ONE story from the CV.
- First line: one sentence naming the situation and the result.
- Then exactly 4 bullets starting "**S:**", "**T:**", "**A:**", "**R:**" (Situation, Task, \
Action, Result), each under 25 words. Action says what I personally did.""",
    "technical": """The question is technical.
- First line: one direct sentence that answers it.
- Then 3 to 5 bullets with the key points in a logical order (steps, components or \
trade-offs), each under 20 words.
- {code}
- If the CV shows relevant hands-on experience, add one final bullet starting \
"**From my experience:**". Otherwise leave it out.
- Never use Situation/Task/Action/Result labels.""",
    "general": """The question is about the candidate: background, motivation, fit or plans.
- First line: one direct sentence that answers it.
- Then 3 or 4 bullets with supporting points, each under 20 words, backed by CV facts \
and the job description when given.
- Never use Situation/Task/Action/Result labels.""",
}

_WORDS = {"behavioral": 140, "technical": 130, "general": 110}

_CODE_YES = (
    "The question asks for code: after the bullets add one short code block (under 20 lines) "
    "in the most fitting language."
)
_CODE_NO = "Don't write code."


def build_messages(
    question: str,
    *,
    kind: Classification,
    context: InterviewContext,
    excerpts: list[ScoredChunk],
    recent_transcript: list[str] | None = None,
) -> list[ChatMessage]:
    fmt = _FORMATS[kind.type]
    if kind.type == "technical":
        fmt = fmt.format(code=_CODE_YES if kind.wants_code else _CODE_NO)
    system = _BASE.format(format=fmt, words=_WORDS[kind.type])

    parts = [f"<cv_profile>\n{context.cv_summary.strip()}\n</cv_profile>"]
    cv_ex = [s for s in excerpts if s.chunk.kind == "cv"]
    jd_ex = [s for s in excerpts if s.chunk.kind == "jd"]
    if cv_ex:
        parts.append(
            "<cv_excerpts>\n" + "\n\n".join(s.chunk.content for s in cv_ex) + "\n</cv_excerpts>"
        )
    if context.jd:
        jd = context.jd.summary.strip()
        if jd_ex:
            jd += "\n\n" + "\n\n".join(s.chunk.content for s in jd_ex)
        parts.append(
            "<job_description>\n(What the EMPLOYER wants. The candidate has NOT necessarily "
            "done any of this; only the CV says what they have done.)\n"
            f"{jd}\n</job_description>"
        )
    if context.gaps:
        parts.append(
            "<not_on_cv>\nThe job asks for these, but the candidate's CV does NOT show them: "
            + ", ".join(g.skill for g in context.gaps)
            + ".\nNever say or imply the candidate has done or used them. If one matters for "
            "the question, say honestly that you're keen to learn it or how your related CV "
            "experience transfers.\n</not_on_cv>"
        )
    if recent_transcript:
        parts.append("Recent conversation:\n" + "\n".join(recent_transcript[-8:]))
    parts.append(f"Interviewer's question: {question}")
    return [ChatMessage("system", system), ChatMessage("user", "\n\n".join(parts))]

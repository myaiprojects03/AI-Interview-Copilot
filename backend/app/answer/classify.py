"""Classify an interview question so the answer uses the right template.

- behavioral: asks for a real past story -> STAR (Situation, Task, Action, Result)
- technical:  concepts, design, tools, code -> key points in order (+ code if asked)
- general:    about you, motivation, fit -> direct answer + supporting points

Rule-based on purpose: instant, free, and predictable. Checked against evals/questions.json.
"""

import re
from dataclasses import dataclass
from typing import Literal

QuestionType = Literal["behavioral", "technical", "general"]


@dataclass(frozen=True)
class Classification:
    type: QuestionType
    wants_code: bool


def _rx(*patterns: str) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in patterns))


_BEHAVIORAL = _rx(
    r"\b(tell|talk) (me|us) about a (time|situation|moment|project|conflict|mistake|failure)",
    r"\b(describe|share|walk me through|tell me about) (a|an|one) "
    r"(time|situation|example|occasion)",
    r"\bgive (me |us )?(a |an )?(specific )?example (of|from|where|when)",
    r"\bcan you (share|give) an example",
    r"\bexample of (a|an) (project|time|situation)",
    r"\bhave you ever\b",
    r"\bcan you recall\b",
    r"\bwhat did you do when\b",
    r"\bhow did you (handle|deal|manage|resolve|approach|respond|overcome|convince|cope|recover)",
    r"\b(hardest|toughest|most difficult|most challenging|biggest|worst) "
    r"(production |technical )?(incident|bug|problem|challenge|mistake|failure|project|conflict|"
    r"decision|setback)",
    r"\bmost challenging project\b",
    r"\b(proudest|most proud)\b",
    r"\bbiggest (achievement|accomplishment|mistake|failure|regret)\b",
    r"\btime (when )?you (had|were|failed|disagreed|received|made|led|missed|took)",
)

_GENERAL = _rx(
    r"\b(about yourself|introduce yourself|your background)\b",
    r"\bwalk me through your (resume|cv|background|career)",
    r"\bweakness", r"\bstrengths?\b",
    r"\bwhy (do you want|are you (leaving|looking|interested)|should we|did you (leave|apply)"
    r"|this (role|company|job)|us\b|here\b)",
    r"\bwhere do you see yourself\b", r"\bfive years\b",
    r"\bsalary\b", r"\bnotice period\b", r"\bcompensation\b",
    r"\bquestions for (us|me)\b", r"\bany questions\b",
    r"\bmotivat", r"\bculture\b", r"\bwork(ing)? style\b", r"\bcareer goals?\b",
    r"\bwhat are you looking for\b", r"\bhobbies\b", r"\bfree time\b",
    r"\bwhat would you do if\b", r"\bhow would you handle (a|an) (difficult|conflict|situation)",
    r"\b(your|my) (experience|background|skills?) (match|fit|align|relate)",
    r"\b(good|right|great|strong) fit\b", r"\bfit (for|with) (this|the|our)\b",
    r"\bwhy (you|should we)\b",
)

_TECHNICAL = _rx(
    r"\bhow would you (design|implement|build|scale|optimi[sz]e|debug|architect|test|model|"
    r"store|structure|secure|migrate|monitor|deploy|handle (traffic|load|failure))",
    r"\bdesign (a|an|the)\b",
    r"\bdifference between\b", r"\btrade-?offs?\b", r"\bcompare\b",
    r"\bexplain\b", r"\bhow does\b", r"\bhow do (you|we|i) (make|implement|ensure|prevent|avoid)",
    r"\bwhat (is|are) (a|an|the)?\s*\w+", r"\bwhat happens when\b",
    r"\bwrite (a|an|some)\b", r"\bimplement (a|an)\b",
    r"\btime complexity\b", r"\bbig o\b",
    r"\b(your|any) experience (with|in|using)\b",
    r"\bhow did you (design|build|implement|architect|scale)\b",
)

_TECH_TERMS = _rx(
    r"\b(api|apis|sql|nosql|database|index(ing)?|cache|caching|thread|process|concurrency|"
    r"kubernetes|docker|kafka|redis|microservices?|algorithm|latency|throughput|https?|tcp|"
    r"dns|rest|graphql|queue|sharding|replication|consistency|python|java|javascript|"
    r"typescript|go|golang|react|aws|azure|gcp|linked list|array|hash|tree|graph|recursion|"
    r"memory leak|garbage collection|oop|solid|design pattern)\b",
)

_CODE = _rx(
    r"\bwrite (a |an |some )?(\w+ )?(function|program|query|script|class|method|code|algorithm)",
    r"\b(sql|code|pseudo-?code) (query|snippet|for)\b", r"\bwrite (a |an )?sql\b",
    r"\bimplement (a|an) (function|method|class|algorithm)",
    r"\bcan you code\b", r"\bin code\b",
)


def classify(question: str, focus: str = "mixed") -> Classification:
    q = " ".join(question.lower().split())
    wants_code = bool(_CODE.search(q))
    if wants_code:
        kind: QuestionType = "technical"
    elif _BEHAVIORAL.search(q):
        kind = "behavioral"
    elif _GENERAL.search(q):
        kind = "general"
    elif _TECHNICAL.search(q) or _TECH_TERMS.search(q):
        kind = "technical"
    else:
        kind = "technical" if focus == "technical" else "general"
    return Classification(kind, wants_code and kind == "technical")

import json
from pathlib import Path

import pytest

from app.answer.classify import classify

QUESTIONS = json.loads(
    (Path(__file__).resolve().parents[1] / "evals" / "questions.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("item", QUESTIONS, ids=[q["q"][:50] for q in QUESTIONS])
def test_question_set(item):
    result = classify(item["q"])
    assert result.type == item["type"]
    assert result.wants_code == item.get("code", False)


def test_question_set_covers_every_type():
    types = {q["type"] for q in QUESTIONS}
    assert types == {"behavioral", "technical", "general"}
    assert sum(q.get("code", False) for q in QUESTIONS) >= 3


def test_focus_breaks_ties_only():
    assert classify("Tell me more.", focus="technical").type == "technical"
    assert classify("Tell me more.").type == "general"
    # A clear behavioral question stays behavioral whatever the focus.
    assert classify("Tell me about a time you failed.", focus="technical").type == "behavioral"

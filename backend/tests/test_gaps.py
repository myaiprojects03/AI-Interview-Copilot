import json

from app.answer.classify import Classification
from app.answer.gaps import SkillGap, _parse, find_gaps, mentioned_gaps, verify
from app.answer.prompts import build_messages
from app.answer.retrieval import InterviewContext
from app.providers.base import ChatMessage, LLMProvider, ProviderError

CV = """Sara Khan. Full-stack engineer: TypeScript, React, Node.js, PostgreSQL.
Cut API latency with Redis caching. Wrote an incident runbook. Let's go live weekly."""

GAPS = [
    SkillGap("AWS", ("AWS", "Amazon Web Services")),
    SkillGap("Go", ("Go", "Golang")),
    SkillGap("Mentoring", ("mentor", "mentoring", "mentored")),
    SkillGap("Design reviews", ("design review", "design reviews")),
]


class ScriptedLLM(LLMProvider):
    name = "scripted"

    def __init__(self, reply: str | Exception):
        self.reply, self.calls = reply, 0

    async def stream_chat(self, messages: list[ChatMessage], **kw):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        yield self.reply


def test_mentions_whole_words_case_rules_and_word_forms():
    answer = (
        "I'd go deep on Go and Golang, deployed on AWS-hosted services, and I mentored two "
        "juniors through design-reviews. Ago, aws and Google don't count."
    )
    found = {g["skill"]: g["matches"] for g in mentioned_gaps(answer, GAPS)}
    assert found == {
        "AWS": ["AWS"],
        "Go": ["Go", "Golang"],
        "Mentoring": ["mentored"],
        "Design reviews": ["design-reviews"],
    }


def test_skills_named_in_the_question_are_not_flagged():
    gaps = [SkillGap("Rate limiting", ("rate limiting", "rate limiter")), GAPS[0]]
    answer = "I'd build a token-bucket rate limiter on AWS."
    found = mentioned_gaps(answer, gaps, question="How would you design a rate limiter?")
    assert found == [{"skill": "AWS", "matches": ["AWS"]}]


def test_lone_generic_words_are_dropped_for_multi_word_skills():
    raw = json.dumps({"gaps": [
        {"skill": "Design reviews", "aliases": ["design review", "review", "reviews"]},
        {"skill": "On-call", "aliases": ["on-call", "on call", "pager"]},
        {"skill": "Mentoring", "aliases": ["mentor", "mentored"]},
        {"skill": "Fraud controls", "aliases": ["fraud", "AML"]},
    ]})
    by_skill = {g.skill: g.aliases for g in _parse(raw)}
    assert by_skill["Design reviews"] == ("Design reviews", "design review")
    assert by_skill["On-call"] == ("On-call", "on-call", "on call", "pager")
    assert by_skill["Mentoring"] == ("Mentoring", "mentor", "mentored")
    assert by_skill["Fraud controls"] == ("Fraud controls", "AML")
    assert mentioned_gaps("We held joint review sessions.", _parse(raw)) == []


def test_verify_drops_skills_the_cv_shows():
    proposed = [
        SkillGap("PostgreSQL", ("PostgreSQL", "Postgres")),
        SkillGap("Redis", ("Redis",)),
        SkillGap("AWS", ("AWS",)),
        SkillGap("aws", ("AWS",)),  # duplicate
        SkillGap("Go", ("Go",)),  # "go live" in the CV is the verb, not the language
    ]
    assert [g.skill for g in verify(proposed, CV)] == ["AWS", "Go"]


def test_parse_tolerates_wrapping_and_bad_items():
    raw = 'Here you go:\n{"gaps": [{"skill": "Kafka", "aliases": ["Kafka", 3]}, {"nope": 1}, ' \
          '{"skill": "AWS"}]}\nThanks'
    assert _parse(raw) == [SkillGap("Kafka", ("Kafka",)), SkillGap("AWS", ("AWS",))]
    assert _parse("no json here") == []
    assert _parse("{broken") == []


async def test_find_gaps_verifies_and_caches():
    reply = json.dumps({"gaps": [{"skill": "AWS", "aliases": ["AWS"]},
                                 {"skill": "React", "aliases": ["React"]}]})
    llm = ScriptedLLM(reply)
    first = await find_gaps(llm, cv_text=CV, jd_text="AWS and React", cache_key=("cv", "jd-1"))
    again = await find_gaps(llm, cv_text=CV, jd_text="AWS and React", cache_key=("cv", "jd-1"))
    assert [g.skill for g in first] == ["AWS"]  # React is on the CV
    assert again == first and llm.calls == 1


async def test_find_gaps_failure_means_no_gaps():
    assert await find_gaps(ScriptedLLM(ProviderError("down")), cv_text=CV, jd_text="x") == []


def test_prompt_lists_gaps_explicitly():
    ctx = InterviewContext(sample_cv_text=CV, gaps=GAPS)
    user = build_messages("Why should we hire you?", kind=Classification("general", False),
                          context=ctx, excerpts=[])[1].content
    assert "does NOT show them: AWS, Go, Mentoring, Design reviews." in user
    assert ctx.public()["gaps"] == ["AWS", "Go", "Mentoring", "Design reviews"]

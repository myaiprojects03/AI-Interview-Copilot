from app.answer.classify import Classification
from app.answer.prompts import SAMPLE_CV, build_messages
from app.answer.retrieval import InterviewContext, load_context, retrieve
from app.documents.service import ingest
from app.documents.store import MemoryStore
from app.providers.embeddings.fake import FakeEmbeddings
from app.providers.llm.fake import FakeLLM

JD = """Staff Engineer, Lumen Pay
Requirements
- Design rate limiting and quota systems for public APIs
- Lead incident response for payment outages
"""


async def setup():
    store, emb, llm = MemoryStore(), FakeEmbeddings(), FakeLLM()
    cv = await ingest(user_id="u1", kind="cv", text=SAMPLE_CV, filename=None, title=None,
                      store=store, embedder=emb, llm=llm)
    jd = await ingest(user_id="u1", kind="jd", text=JD, filename=None, title="Lumen",
                      store=store, embedder=emb, llm=llm)
    return store, emb, cv, jd


async def test_retrieves_the_relevant_role():
    store, emb, cv, jd = await setup()
    ctx = await load_context(store, "u1", cv_id=cv.id, jd_id=jd.id, sample_cv_text="")
    hits = await retrieve(ctx, emb, "How would you design rate limiting for a public partner API?")
    cv_hits = [h for h in hits if h.chunk.kind == "cv"]
    assert "rate limiting" in cv_hits[0].chunk.content
    assert "Kitecart" in cv_hits[0].label
    assert any(h.chunk.kind == "jd" for h in hits)
    assert len(cv_hits) <= 4


async def test_latest_and_user_scoping():
    store, emb, cv, jd = await setup()
    mine = await load_context(store, "u1", cv_id="latest", jd_id="latest", sample_cv_text="x")
    assert mine.cv.id == cv.id and mine.jd.id == jd.id
    theirs = await load_context(store, "u2", cv_id=cv.id, jd_id="latest", sample_cv_text="x")
    assert theirs.cv is None and theirs.jd is None and theirs.chunks == []
    assert theirs.public()["using_sample_cv"] is True


async def test_prompt_contains_profile_excerpts_and_job():
    store, emb, cv, jd = await setup()
    ctx = await load_context(store, "u1", cv_id=cv.id, jd_id=jd.id, sample_cv_text="")
    hits = await retrieve(ctx, emb, "Tell me about a time you handled an outage.")
    msgs = build_messages(
        "Tell me about a time you handled an outage.",
        kind=Classification("behavioral", False),
        context=ctx,
        excerpts=hits,
    )
    system, user = msgs[0].content, msgs[1].content
    assert "**S:**" in system and "Don't write code" not in system
    assert "<cv_profile>" in user and "<cv_excerpts>" in user and "<job_description>" in user
    assert user.rstrip().endswith("Tell me about a time you handled an outage.")


def test_technical_prompt_asks_for_code_only_when_requested():
    ctx = InterviewContext(sample_cv_text=SAMPLE_CV)
    with_code = build_messages("q", kind=Classification("technical", True), context=ctx,
                               excerpts=[])[0].content
    no_code = build_messages("q", kind=Classification("technical", False), context=ctx,
                             excerpts=[])[0].content
    assert "code block" in with_code and "Don't write code." in no_code


async def test_sample_cv_context_has_no_chunks_but_full_profile():
    ctx = InterviewContext(sample_cv_text=SAMPLE_CV)
    assert await retrieve(ctx, FakeEmbeddings(), "anything") == []
    assert "Brightlane" in ctx.cv_summary
    assert "Brightlane" in ctx.fact_text

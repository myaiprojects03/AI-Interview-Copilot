import json

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.core.config import Settings
from app.providers.base import ChatMessage, ProviderError
from app.providers.llm.groq import GroqLLM
from app.providers.registry import get_llm, get_stt, provider_status
from app.providers.stt.groq import GroqWhisperSTT

BASE = "https://api.groq.test/openai/v1"


async def test_fake_llm_streams_tokens(settings):
    llm = get_llm(settings)
    parts = [p async for p in llm.stream_chat([ChatMessage("user", "hi")])]
    assert len(parts) > 1
    assert "fake suggestion" in "".join(parts)


async def test_fake_stt(settings):
    result = await get_stt(settings).transcribe(b"\x00" * 10)
    assert result.text == "Tell me about yourself."


def test_groq_requires_key():
    s = Settings(_env_file=None, llm_provider="groq", groq_api_key=None)
    with pytest.raises(ProviderError, match="GROQ_API_KEY"):
        get_llm(s)


def test_provider_status_never_leaks_key():
    s = Settings(_env_file=None, groq_api_key=SecretStr("gsk_supersecret"))
    status = provider_status(s)
    assert status["llm"]["configured"] is True
    assert "gsk_supersecret" not in json.dumps(status)


@respx.mock
async def test_groq_llm_parses_sse_stream():
    events = [
        {"choices": [{"delta": {"role": "assistant"}}]},
        {"choices": [{"delta": {"content": "Hello"}}]},
        {"choices": [{"delta": {"content": " world"}}]},
    ]
    sse = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, text=sse)
    )
    llm = GroqLLM(api_key="test", model="m", base_url=BASE)
    parts = [p async for p in llm.stream_chat([ChatMessage("user", "hi")])]
    assert parts == ["Hello", " world"]
    sent = json.loads(route.calls[0].request.content)
    assert sent["stream"] is True and sent["model"] == "m"


@respx.mock
async def test_groq_llm_sends_reasoning_effort_only_when_set():
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, text="data: [DONE]\n\n")
    )
    for effort in ("low", None):
        llm = GroqLLM(api_key="test", model="m", base_url=BASE, reasoning_effort=effort)
        [p async for p in llm.stream_chat([ChatMessage("user", "hi")])]
    first, second = (json.loads(c.request.content) for c in route.calls)
    assert first["reasoning_effort"] == "low"
    assert "reasoning_effort" not in second


@respx.mock
async def test_groq_llm_http_error_is_provider_error():
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(429, text="rate limited")
    )
    llm = GroqLLM(api_key="test", model="m", base_url=BASE)
    with pytest.raises(ProviderError, match="429"):
        [p async for p in llm.stream_chat([ChatMessage("user", "hi")])]


@respx.mock
async def test_groq_stt_returns_transcript():
    respx.post(f"{BASE}/audio/transcriptions").mock(
        return_value=httpx.Response(
            200, json={"text": " Why do you want this job? ", "language": "en", "duration": 2.1}
        )
    )
    stt = GroqWhisperSTT(api_key="test", model="w", base_url=BASE)
    result = await stt.transcribe(b"RIFF....")
    assert result.text == "Why do you want this job?"
    assert result.duration_seconds == 2.1

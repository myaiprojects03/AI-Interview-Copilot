"""Build providers from settings. Swap a provider by changing LLM_PROVIDER / STT_PROVIDER."""

from pydantic import SecretStr

from app.core.config import Settings
from app.providers.base import EmbeddingProvider, LLMProvider, ProviderError, STTProvider


def _has(secret: SecretStr | None) -> bool:
    return secret is not None and bool(secret.get_secret_value())


def _groq_key(settings: Settings) -> str:
    if not _has(settings.groq_api_key):
        raise ProviderError("GROQ_API_KEY is not set. Add it to your .env file.")
    return settings.groq_api_key.get_secret_value()


def get_llm(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "fake":
        from app.providers.llm.fake import FakeLLM

        return FakeLLM()
    from app.providers.llm.groq import GroqLLM

    return GroqLLM(
        api_key=_groq_key(settings),
        model=settings.groq_llm_model,
        base_url=settings.groq_base_url,
        timeout=settings.request_timeout_seconds,
        reasoning_effort=settings.groq_reasoning_effort,
    )


def get_stt(settings: Settings) -> STTProvider:
    if settings.stt_provider == "fake":
        from app.providers.stt.fake import FakeSTT

        return FakeSTT()
    from app.providers.stt.groq import GroqWhisperSTT

    return GroqWhisperSTT(
        api_key=_groq_key(settings),
        model=settings.groq_stt_model,
        base_url=settings.groq_base_url,
        timeout=settings.request_timeout_seconds,
    )


def get_embedder(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "fake":
        from app.providers.embeddings.fake import FakeEmbeddings

        return FakeEmbeddings()
    from app.providers.embeddings.local import LocalEmbeddings

    return LocalEmbeddings(settings.embedding_model, cache_dir=settings.model_cache_dir)


def provider_status(settings: Settings) -> dict:
    """Which providers are selected and whether their keys are present. Never returns secrets."""
    groq_ready = _has(settings.groq_api_key)
    return {
        "llm": {
            "provider": settings.llm_provider,
            "model": settings.groq_llm_model if settings.llm_provider == "groq" else None,
            "configured": settings.llm_provider == "fake" or groq_ready,
        },
        "stt": {
            "provider": settings.stt_provider,
            "model": settings.groq_stt_model if settings.stt_provider == "groq" else None,
            "configured": settings.stt_provider == "fake" or groq_ready,
        },
        "embeddings": {"provider": settings.embedding_provider, "configured": True},
        "database": {"configured": _has(settings.database_url)},
    }

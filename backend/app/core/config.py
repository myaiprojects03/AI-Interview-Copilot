"""All runtime settings come from environment variables (or a local .env file).

Secrets are never hard-coded. Providers are chosen by name so they can be swapped by config.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Same file whichever folder the server is started from.
        env_file=(BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI Interview Copilot"
    environment: Literal["development", "staging", "production", "test"] = "development"
    cors_origins: list[str] = ["http://localhost:3000"]

    # Provider selection ("fake" providers need no keys and are used in tests).
    llm_provider: Literal["groq", "fake"] = "groq"
    stt_provider: Literal["groq", "fake"] = "groq"

    # Groq (free tier): LLM + Whisper speech-to-text.
    groq_api_key: SecretStr | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_llm_model: str = "openai/gpt-oss-120b"
    # Reasoning models think before answering; "low" keeps first-token latency under ~0.5 s.
    # Leave empty for models that don't support it.
    groq_reasoning_effort: Literal["none", "low", "medium", "high"] | None = "low"
    groq_stt_model: str = "whisper-large-v3-turbo"

    # Google Gemini (free tier), optional LLM fallback, wired in a later phase.
    gemini_api_key: SecretStr | None = None

    # Supabase Postgres + pgvector (free tier), used from Phase 2.
    database_url: SecretStr | None = None

    request_timeout_seconds: float = 30.0

    # Real-time pipeline tuning.
    vad_silence_ms: int = 800  # quiet time that ends an utterance
    vad_threshold_db: float = -45.0
    # Partial transcripts re-send the in-progress audio to STT every N ms (interviewer only).
    # Each partial is one extra STT request against the free-tier rate limit; 0 turns them off.
    stt_partial_interval_ms: int = 2000
    answer_max_tokens: int = 700


@lru_cache
def get_settings() -> Settings:
    return Settings()

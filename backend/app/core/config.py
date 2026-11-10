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

    # Supabase Postgres + pgvector (free tier). Without it, documents live in memory and are
    # lost on restart (fine for tests and a first try, not for real use).
    database_url: SecretStr | None = None

    # Local embeddings (fastembed, free). "fake" is a keyword-hash stand-in for tests.
    embedding_provider: Literal["local", "fake"] = "local"
    embedding_model: str = "BAAI/bge-small-en-v1.5"

    # Sign-in (Supabase Auth). When neither is set and environment is development/test,
    # every request acts as `dev_user_id` so the app runs locally without accounts.
    supabase_url: str | None = None  # tokens are checked against this project's public keys
    supabase_jwt_secret: SecretStr | None = None  # only for projects on legacy HS256 secrets
    dev_user_id: str = "local-dev"

    # Billing. "fake" simulates subscribe / upgrade / cancel instantly (dev and tests);
    # "paddle" uses Paddle Billing (sandbox or live).
    billing_provider: Literal["paddle", "fake"] = "fake"
    paddle_api_key: SecretStr | None = None
    paddle_environment: Literal["sandbox", "production"] = "sandbox"
    paddle_webhook_secret: SecretStr | None = None
    paddle_price_starter: str | None = None
    paddle_price_pro: str | None = None
    app_url: str = "http://localhost:3000"  # where billing redirects users back to

    # Comma-separated emails that can open the admin latency view.
    admin_emails: str = ""

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    @property
    def auth_enabled(self) -> bool:
        secret = self.supabase_jwt_secret
        return bool(self.supabase_url) or bool(secret and secret.get_secret_value())

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

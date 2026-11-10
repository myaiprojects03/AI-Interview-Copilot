import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.accounts.store import MemoryAccountStore, PostgresAccountStore
from app.api import billing, documents, health, history, realtime
from app.api.billing import make_billing
from app.core.auth import TokenVerifier
from app.core.config import Settings, get_settings
from app.documents.store import DocumentStore, MemoryStore, PostgresStore
from app.providers.embeddings.local import LocalEmbeddings
from app.providers.registry import get_embedder

log = logging.getLogger("app")


async def _open_store(settings: Settings) -> tuple[DocumentStore, str | None]:
    if settings.database_url is None or not settings.database_url.get_secret_value():
        return MemoryStore(), None
    try:
        return await PostgresStore.connect(settings.database_url.get_secret_value()), None
    except Exception as exc:  # noqa: BLE001 - report any connection problem, keep serving
        message = f"{exc.__class__.__name__}: {exc}"[:300]
        log.error("Database connection failed, documents will be kept in memory: %s", message)
        return MemoryStore(), message


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store, app.state.store_error = await _open_store(settings)
        app.state.accounts = (
            PostgresAccountStore(app.state.store.pool)
            if isinstance(app.state.store, PostgresStore)
            else MemoryAccountStore()
        )
        app.state.verifier = TokenVerifier(settings)
        app.state.billing = make_billing(settings)
        if not settings.auth_enabled:
            log.warning("Sign-in is not configured: every request acts as %s", settings.dev_user_id)
        app.state.embedder = get_embedder(settings)
        warm = None
        if isinstance(app.state.embedder, LocalEmbeddings):
            warm = asyncio.create_task(app.state.embedder.warm_up())
        try:
            yield
        finally:
            if warm:
                warm.cancel()
            await app.state.store.close()

    app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(documents.router)
    app.include_router(billing.router)
    app.include_router(history.router)
    app.include_router(realtime.router)
    return app


app = create_app()

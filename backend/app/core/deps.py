"""Shared FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends
from starlette.requests import HTTPConnection

from app.core.config import Settings, get_settings
from app.documents.store import DocumentStore
from app.providers.base import EmbeddingProvider

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_store(conn: HTTPConnection) -> DocumentStore:
    return conn.app.state.store


def get_embedder_dep(conn: HTTPConnection) -> EmbeddingProvider:
    return conn.app.state.embedder


def current_user_id(settings: SettingsDep) -> str:
    """Placeholder until sign-in (Phase 3): everyone is the single dev user."""
    return settings.dev_user_id


StoreDep = Annotated[DocumentStore, Depends(get_store)]
EmbedderDep = Annotated[EmbeddingProvider, Depends(get_embedder_dep)]
UserDep = Annotated[str, Depends(current_user_id)]

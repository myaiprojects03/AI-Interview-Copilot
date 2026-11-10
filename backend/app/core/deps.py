"""Shared FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends, HTTPException
from starlette.requests import HTTPConnection

from app.core.auth import AuthError, TokenVerifier, User
from app.core.config import Settings, get_settings
from app.documents.store import DocumentStore
from app.providers.base import EmbeddingProvider

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_store(conn: HTTPConnection) -> DocumentStore:
    return conn.app.state.store


def get_embedder_dep(conn: HTTPConnection) -> EmbeddingProvider:
    return conn.app.state.embedder


def get_accounts(conn: HTTPConnection):
    return conn.app.state.accounts


def get_verifier(conn: HTTPConnection, settings: SettingsDep) -> TokenVerifier:
    verifier = getattr(conn.app.state, "verifier", None)
    if verifier is None:
        verifier = conn.app.state.verifier = TokenVerifier(settings)
    return verifier


async def authenticate(token: str | None, settings: Settings, verifier: TokenVerifier) -> User:
    """Shared by HTTP requests and the WebSocket. Raises AuthError."""
    if not settings.auth_enabled:
        if settings.environment in ("development", "test"):
            return User(id=settings.dev_user_id, email="dev@localhost")
        raise AuthError("Sign-in isn't configured on the server.")
    return await verifier.verify(token)


async def current_user(
    conn: HTTPConnection,
    settings: SettingsDep,
    verifier: Annotated[TokenVerifier, Depends(get_verifier)],
) -> User:
    header = conn.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else None
    try:
        return await authenticate(token, settings, verifier)
    except AuthError as exc:
        raise HTTPException(
            status_code=401, detail=str(exc), headers={"WWW-Authenticate": "Bearer"}
        ) from exc


async def current_user_id(user: Annotated[User, Depends(current_user)]) -> str:
    return user.id


StoreDep = Annotated[DocumentStore, Depends(get_store)]
EmbedderDep = Annotated[EmbeddingProvider, Depends(get_embedder_dep)]
CurrentUser = Annotated[User, Depends(current_user)]
UserDep = Annotated[str, Depends(current_user_id)]
VerifierDep = Annotated[TokenVerifier, Depends(get_verifier)]

"""Check Supabase sign-in tokens (JWTs).

The browser signs in with Supabase and sends the access token on every request
("Authorization: Bearer ...", or as the first WebSocket message). Projects created since
2025 sign tokens with asymmetric keys published at /auth/v1/.well-known/jwks.json; older
projects use a shared HS256 secret. Both are supported.
"""

import asyncio
from dataclasses import dataclass

import jwt
from jwt import PyJWKClient

from app.core.config import Settings

AUDIENCE = "authenticated"


class AuthError(Exception):
    """The token is missing, malformed, expired or not signed by our project."""


@dataclass(frozen=True)
class User:
    id: str
    email: str | None = None


class TokenVerifier:
    def __init__(self, settings: Settings):
        self._secret = (
            settings.supabase_jwt_secret.get_secret_value()
            if settings.supabase_jwt_secret
            else None
        )
        self._jwks = (
            PyJWKClient(
                f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json",
                cache_keys=True,
                lifespan=3600,
                timeout=10,
            )
            if settings.supabase_url
            else None
        )

    async def verify(self, token: str | None) -> User:
        if not token:
            raise AuthError("Sign in to continue.")
        try:
            alg = jwt.get_unverified_header(token).get("alg")
        except jwt.PyJWTError as exc:
            raise AuthError("Invalid sign-in token.") from exc

        if alg == "HS256":
            if not self._secret:
                raise AuthError("Invalid sign-in token.")
            key = self._secret
        elif alg in ("ES256", "RS256", "EdDSA") and self._jwks:
            try:
                signing_key = await asyncio.to_thread(self._jwks.get_signing_key_from_jwt, token)
            except jwt.PyJWTError as exc:
                raise AuthError("Invalid sign-in token.") from exc
            key = signing_key.key
        else:
            raise AuthError("Invalid sign-in token.")

        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[alg],
                audience=AUDIENCE,
                options={"require": ["exp", "sub"]},
                leeway=30,
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthError("Your session expired. Sign in again.") from exc
        except jwt.PyJWTError as exc:
            raise AuthError("Invalid sign-in token.") from exc
        return User(id=str(claims["sub"]), email=claims.get("email"))

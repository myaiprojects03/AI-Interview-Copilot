import time

import jwt

SECRET = "test-jwt-secret-that-is-long-enough-for-hs256"


def token(sub: str = "user-1", email: str = "u1@example.com", secret: str = SECRET,
          exp_in: int = 3600, aud: str = "authenticated") -> str:
    return jwt.encode(
        {"sub": sub, "email": email, "aud": aud, "exp": int(time.time()) + exp_in},
        secret,
        algorithm="HS256",
    )


def auth(sub: str = "user-1") -> dict:
    return {"Authorization": f"Bearer {token(sub)}"}

"""
Supabase Auth token verification.

Replaces Flask-Login: identity now comes from a JWT the client obtained from
Supabase Auth, not from a server-side session cookie. The project signs tokens
with ES256, so verification uses the public JWKS endpoint - there is no shared
secret to store, and nothing here can mint a token.

Note that profiles has no email column. Email lives on auth.users and reaches us
through the token claims, which is why AuthenticatedUser carries it.
"""
import os
from dataclasses import dataclass

import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL environment variable is not set")

JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"

# Supabase tokens carry aud="authenticated" and iss=<project>/auth/v1
JWT_AUDIENCE = "authenticated"
JWT_ISSUER = f"{SUPABASE_URL}/auth/v1"

# Caches the signing keys and refetches when an unknown kid appears, so key
# rotation doesn't need a redeploy and every request isn't an HTTP round trip.
_jwk_client = PyJWKClient(JWKS_URL, cache_keys=True)

# auto_error=False so the same scheme backs both required and optional auth;
# the dependencies below decide what a missing header means.
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email: str | None


def _decode(token: str) -> AuthenticatedUser:
    try:
        signing_key = _jwk_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience=JWT_AUDIENCE,
            issuer=JWT_ISSUER,
            # Defence in depth: a token without sub is unusable, and expiry must
            # be present rather than merely valid-if-present
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return AuthenticatedUser(id=claims["sub"], email=claims.get("email"))


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthenticatedUser:
    """Require a valid token. Use on endpoints that must know who is calling."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _decode(credentials.credentials)


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthenticatedUser | None:
    """
    Identify the caller if a token is present, otherwise return None.

    For endpoints that serve everyone but enrich the response when signed in -
    phase 5 uses this to add shares_owned to the artist detail response.
    A malformed token is still rejected: only its absence is tolerated.
    """
    if credentials is None:
        return None
    return _decode(credentials.credentials)

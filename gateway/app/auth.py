"""Checks the access token at the edge.

The gateway doesn't decide who may do what; each service still checks roles itself.
It does two things with the token:
- a bad or expired token is refused here, before any service spends time on it
  (the services would refuse it too, with the same 401, so the storefront's
  refresh-and-retry works the same way);
- a good token gives the user's id, so rate limits follow the person, not their IP.
"""

from dataclasses import dataclass

import jwt

from .config import get_settings

ALGORITHM = "HS256"


class BadToken(Exception):
    pass


@dataclass(frozen=True)
class Identity:
    user_id: str
    role: str


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise BadToken("Authorization header must be 'Bearer <token>'.")
    return token.strip()


def identify(authorization: str | None) -> Identity | None:
    """None for anonymous requests; raises BadToken for a token that doesn't check out."""
    token = bearer_token(authorization)
    if token is None:
        return None
    try:
        claims = jwt.decode(
            token,
            get_settings().jwt_signing_key,
            algorithms=[ALGORITHM],  # never "none" or anything else
            options={"require": ["exp", "user_id", "token_type"]},
        )
    except jwt.ExpiredSignatureError:
        raise BadToken("Token has expired.")
    except jwt.InvalidTokenError:
        raise BadToken("Token is invalid.")
    if claims.get("token_type") != "access":
        raise BadToken("Not an access token.")
    return Identity(user_id=str(claims["user_id"]), role=str(claims.get("role", "")))

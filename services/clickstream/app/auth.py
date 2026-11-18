"""Optional sign-in for analytics.

Tokens are issued by the users service. Shoppers browse without signing in, so a missing,
expired or broken token is not an error here: the event is recorded as anonymous.
"""

import uuid

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings

ALGORITHM = "HS256"
bearer = HTTPBearer(auto_error=False)


def signed_in_user_id(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> uuid.UUID | None:
    if credentials is None:
        return None
    try:
        claims = jwt.decode(
            credentials.credentials,
            get_settings().jwt_signing_key,
            algorithms=[ALGORITHM],  # never accept "none" or other algorithms
            options={"require": ["exp", "user_id", "token_type"]},
        )
    except jwt.InvalidTokenError:
        return None
    if claims.get("token_type") != "access":
        return None
    try:
        return uuid.UUID(str(claims["user_id"]))
    except ValueError:
        return None

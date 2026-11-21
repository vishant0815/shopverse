"""Seller sign-in for the analytics API.

Tokens are issued by the users service and checked here with the same key. Only an access token
for a seller gets through: a customer's token, a refresh token and an expired token are refused.
"""

import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings

ALGORITHM = "HS256"  # never accept "none" or other algorithms
bearer = HTTPBearer(auto_error=False)

SIGN_IN_AGAIN = "Sign in again to see your analytics."


def _refuse(status_code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def seller_id(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> uuid.UUID:
    if credentials is None:
        raise _refuse(status.HTTP_401_UNAUTHORIZED, SIGN_IN_AGAIN)
    try:
        claims = jwt.decode(
            credentials.credentials,
            get_settings().jwt_signing_key,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "user_id", "token_type", "role"]},
        )
    except jwt.InvalidTokenError:
        raise _refuse(status.HTTP_401_UNAUTHORIZED, SIGN_IN_AGAIN)
    if claims.get("token_type") != "access":
        raise _refuse(status.HTTP_401_UNAUTHORIZED, SIGN_IN_AGAIN)
    if claims.get("role") != "seller":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only sellers can see analytics.")
    try:
        return uuid.UUID(str(claims["user_id"]))
    except ValueError:
        raise _refuse(status.HTTP_401_UNAUTHORIZED, SIGN_IN_AGAIN)

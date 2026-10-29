"""JWT handling.

Customer tokens are issued by the users service; this service only verifies them.
For calling the orders service, it signs its own short-lived token with role "service".
"""

import time
import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings

ALGORITHM = "HS256"
# Fixed id that identifies this service in other services' audit logs.
SERVICE_USER_ID = "00000000-0000-4000-8000-0000000000fa"

bearer = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    id: uuid.UUID
    role: str
    token: str


def decode_access_token(token: str) -> dict:
    claims = jwt.decode(
        token,
        get_settings().jwt_signing_key,
        algorithms=[ALGORITHM],  # never accept "none" or other algorithms
        options={"require": ["exp", "user_id", "token_type"]},
    )
    if claims.get("token_type") != "access":
        raise jwt.InvalidTokenError("Not an access token")
    return claims


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> CurrentUser:
    unauthorised = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="A valid access token is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorised
    try:
        claims = decode_access_token(credentials.credentials)
        return CurrentUser(id=uuid.UUID(str(claims["user_id"])), role=claims.get("role", ""), token=credentials.credentials)
    except (jwt.InvalidTokenError, ValueError):
        raise unauthorised


def service_token(lifetime_seconds: int = 60) -> str:
    now = int(time.time())
    claims = {
        "token_type": "access",
        "user_id": SERVICE_USER_ID,
        "role": "service",
        "iat": now,
        "exp": now + lifetime_seconds,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, get_settings().jwt_signing_key, algorithm=ALGORITHM)

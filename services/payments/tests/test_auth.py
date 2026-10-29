import time
import uuid

import jwt
import pytest

from app.auth import SERVICE_USER_ID, decode_access_token, service_token

from .conftest import SIGNING_KEY, make_token

URL = "/api/v1/payments/SV-20261029-ABCDEF"


def get_with(client, token):
    return client.get(URL, headers={"Authorization": f"Bearer {token}"})


def test_health_needs_no_login(client):
    assert client.get("/health").json()["status"] == "ok"


def test_missing_token_is_rejected(client):
    assert client.get(URL).status_code == 401


@pytest.mark.parametrize("token", [
    make_token(key="a-different-key-a-different-key-123"),   # forged
    make_token(expires_in=-10),                               # expired
    make_token(token_type="refresh"),                         # wrong kind of token
    "not.a.token",
])
def test_bad_tokens_are_rejected(client, token):
    assert get_with(client, token).status_code == 401


def test_alg_none_is_rejected(client):
    claims = {"token_type": "access", "user_id": str(uuid.uuid4()), "exp": int(time.time()) + 300}
    unsigned = jwt.encode(claims, None, algorithm="none")

    assert get_with(client, unsigned).status_code == 401


def test_valid_token_gets_through_auth(client):
    # 404 means auth passed and the (missing) payment was looked up.
    assert get_with(client, make_token()).status_code == 404


def test_service_token_is_short_lived_and_has_service_role():
    claims = decode_access_token(service_token())

    assert claims["role"] == "service"
    assert claims["user_id"] == SERVICE_USER_ID
    assert claims["exp"] - claims["iat"] <= 60
    assert jwt.decode(service_token(), SIGNING_KEY, algorithms=["HS256"])["token_type"] == "access"

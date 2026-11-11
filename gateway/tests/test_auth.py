import jwt
import pytest

from .conftest import SIGNING_KEY, auth, make_token


def test_anonymous_requests_go_through(gateway, services):
    response = gateway.get("/api/v1/products/")

    assert response.status_code == 200
    assert "authorization" not in services.last.headers


def test_a_valid_token_is_passed_to_the_service(gateway, services):
    token = make_token()

    response = gateway.get("/api/v1/orders/", headers=auth(token))

    assert response.status_code == 200
    # Services still check the token and the role themselves.
    assert services.last.headers["authorization"] == f"Bearer {token}"


@pytest.mark.parametrize("token, message", [
    (make_token(expires_in=-10), "Token has expired."),
    (make_token(key="another-key-that-is-also-long-enough-123"), "Token is invalid."),
    (make_token(token_type="refresh"), "Not an access token."),
    ("not.a.jwt", "Token is invalid."),
])
def test_bad_tokens_are_refused_at_the_door(gateway, services, token, message):
    response = gateway.get("/api/v1/orders/", headers=auth(token))

    assert response.status_code == 401
    assert response.json() == {"detail": message, "code": "token_not_valid"}
    assert response.headers["www-authenticate"] == "Bearer"
    assert services.received == []


def test_unsigned_tokens_are_refused(gateway, services):
    token = jwt.encode({"token_type": "access", "user_id": "x", "exp": 9999999999}, None, algorithm="none")

    response = gateway.get("/api/v1/orders/", headers=auth(token))

    assert response.status_code == 401
    assert services.received == []


def test_tokens_signed_with_another_algorithm_are_refused(gateway, services):
    token = make_token(key=SIGNING_KEY + "x" * 40, algorithm="HS512")

    response = gateway.get("/api/v1/orders/", headers=auth(token))

    assert response.status_code == 401


def test_a_token_missing_required_claims_is_refused(gateway, services):
    token = jwt.encode({"token_type": "access", "exp": 9999999999}, SIGNING_KEY, algorithm="HS256")

    response = gateway.get("/api/v1/orders/", headers=auth(token))

    assert response.status_code == 401


@pytest.mark.parametrize("header", ["Token abc", "Bearer", "Bearer   ", "Basic dXNlcjpwYXNz"])
def test_a_malformed_authorization_header_is_refused(gateway, services, header):
    response = gateway.get("/api/v1/orders/", headers={"Authorization": header})

    assert response.status_code == 401
    assert services.received == []

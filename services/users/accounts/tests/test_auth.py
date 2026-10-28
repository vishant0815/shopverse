import pytest
from django.conf import settings
from rest_framework.throttling import ScopedRateThrottle

from accounts.models import User

from .conftest import PASSWORD

REGISTER = "/api/v1/auth/register/"
LOGIN = "/api/v1/auth/login/"
REFRESH = "/api/v1/auth/refresh/"
LOGOUT = "/api/v1/auth/logout/"
ME = "/api/v1/users/me/"
COOKIE = settings.REFRESH_COOKIE_NAME

pytestmark = pytest.mark.django_db


def register_payload(**overrides):
    data = {"email": "Bob@Example.com", "password": PASSWORD, "first_name": "Bob"}
    data.update(overrides)
    return data


class TestRegister:
    def test_creates_customer_and_returns_tokens(self, api_client):
        response = api_client.post(REGISTER, register_payload())

        assert response.status_code == 201
        assert response.data["user"]["email"] == "bob@example.com"
        assert response.data["user"]["role"] == "customer"
        assert "access" in response.data
        assert "password" not in response.data["user"]

    def test_refresh_token_is_set_in_httponly_cookie_not_body(self, api_client):
        response = api_client.post(REGISTER, register_payload())

        assert "refresh" not in response.data
        cookie = response.cookies[COOKIE]
        assert cookie["httponly"]
        assert cookie["samesite"] == "Lax"
        assert cookie["path"] == "/api/v1/auth/"

    def test_password_is_hashed(self, api_client):
        api_client.post(REGISTER, register_payload())
        user = User.objects.get(email="bob@example.com")

        assert user.password != PASSWORD
        assert user.check_password(PASSWORD)

    def test_can_register_as_seller(self, api_client):
        response = api_client.post(REGISTER, register_payload(role="seller"))

        assert response.status_code == 201
        assert response.data["user"]["role"] == "seller"

    def test_cannot_register_as_admin(self, api_client):
        response = api_client.post(REGISTER, register_payload(role="admin"))

        assert response.status_code == 400
        assert not User.objects.filter(email="bob@example.com").exists()

    def test_duplicate_email_is_rejected_case_insensitively(self, api_client, make_user):
        make_user(email="bob@example.com")
        response = api_client.post(REGISTER, register_payload(email="BOB@example.com"))

        assert response.status_code == 400
        assert "email" in response.data

    @pytest.mark.parametrize("weak", ["short1!", "password123", "12345678901"])
    def test_weak_passwords_are_rejected(self, api_client, weak):
        response = api_client.post(REGISTER, register_payload(password=weak))

        assert response.status_code == 400


class TestLogin:
    def test_valid_credentials_return_access_token(self, api_client, user):
        response = api_client.post(LOGIN, {"email": user.email, "password": PASSWORD})

        assert response.status_code == 200
        assert "access" in response.data
        assert COOKIE in response.cookies

    def test_email_is_case_insensitive(self, api_client, user):
        response = api_client.post(LOGIN, {"email": "ALICE@example.com", "password": PASSWORD})

        assert response.status_code == 200

    def test_wrong_password_and_unknown_email_give_same_error(self, api_client, user):
        wrong_password = api_client.post(LOGIN, {"email": user.email, "password": "nope-nope-1"})
        unknown_email = api_client.post(LOGIN, {"email": "ghost@example.com", "password": PASSWORD})

        assert wrong_password.status_code == unknown_email.status_code == 400
        assert wrong_password.data == unknown_email.data

    def test_inactive_user_cannot_log_in(self, api_client, make_user):
        make_user(email="gone@example.com", is_active=False)
        response = api_client.post(LOGIN, {"email": "gone@example.com", "password": PASSWORD})

        assert response.status_code == 400

    def test_login_is_rate_limited(self, api_client, user, monkeypatch):
        monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {"auth": "3/minute"})
        payload = {"email": user.email, "password": "wrong-password-1"}

        statuses = [api_client.post(LOGIN, payload).status_code for _ in range(4)]

        assert statuses == [400, 400, 400, 429]


class TestRefreshAndLogout:
    def login(self, api_client, user):
        return api_client.post(LOGIN, {"email": user.email, "password": PASSWORD})

    def test_refresh_returns_new_access_and_rotates_cookie(self, api_client, user):
        first = self.login(api_client, user).cookies[COOKIE].value

        response = api_client.post(REFRESH)

        assert response.status_code == 200
        assert "access" in response.data
        assert response.cookies[COOKIE].value != first

    def test_old_refresh_token_cannot_be_reused_after_rotation(self, api_client, user):
        old = self.login(api_client, user).cookies[COOKIE].value
        api_client.post(REFRESH)

        api_client.cookies[COOKIE] = old
        response = api_client.post(REFRESH)

        assert response.status_code == 401

    def test_refresh_without_cookie_is_rejected(self, api_client):
        assert api_client.post(REFRESH).status_code == 401

    def test_refresh_with_garbage_cookie_is_rejected(self, api_client):
        api_client.cookies[COOKIE] = "not-a-token"
        assert api_client.post(REFRESH).status_code == 401

    def test_logout_blacklists_refresh_token_and_clears_cookie(self, api_client, user):
        token = self.login(api_client, user).cookies[COOKIE].value

        response = api_client.post(LOGOUT)
        assert response.status_code == 204
        assert response.cookies[COOKIE].value == ""

        api_client.cookies[COOKIE] = token
        assert api_client.post(REFRESH).status_code == 401

    def test_deactivated_user_cannot_refresh(self, api_client, user):
        self.login(api_client, user)
        user.is_active = False
        user.save()

        assert api_client.post(REFRESH).status_code == 401


class TestTokens:
    def test_access_token_carries_role_claim(self, api_client, make_user):
        from rest_framework_simplejwt.tokens import AccessToken

        seller = make_user(email="seller@example.com", role="seller")
        response = api_client.post(LOGIN, {"email": seller.email, "password": PASSWORD})

        assert AccessToken(response.data["access"])["role"] == "seller"

    def test_protected_endpoint_requires_token(self, api_client):
        assert api_client.get(ME).status_code == 401

    def test_invalid_token_is_rejected(self, api_client):
        api_client.credentials(HTTP_AUTHORIZATION="Bearer invalid.token.here")
        assert api_client.get(ME).status_code == 401

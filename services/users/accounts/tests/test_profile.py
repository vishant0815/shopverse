import pytest
from django.conf import settings

from .conftest import PASSWORD

ME = "/api/v1/users/me/"
CHANGE_PASSWORD = "/api/v1/users/me/change-password/"
LOGIN = "/api/v1/auth/login/"
REFRESH = "/api/v1/auth/refresh/"

pytestmark = pytest.mark.django_db


def test_get_own_profile(auth_client, user):
    response = auth_client.get(ME)

    assert response.status_code == 200
    assert response.data["email"] == user.email
    assert response.data["full_name"] == "Alice"


def test_update_profile(auth_client, user):
    response = auth_client.patch(ME, {"last_name": "Smith", "phone": "+447700900123"})

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.last_name == "Smith"
    assert user.phone == "+447700900123"


def test_cannot_change_role_or_email_through_profile(auth_client, user):
    auth_client.patch(ME, {"role": "admin", "email": "hacker@example.com"})

    user.refresh_from_db()
    assert user.role == "customer"
    assert user.email == "alice@example.com"


def test_put_is_not_allowed(auth_client):
    assert auth_client.put(ME, {"first_name": "X"}).status_code == 405


class TestChangePassword:
    NEW = "An0ther-Str0ng-One!"

    def test_changes_password(self, auth_client, user, api_client):
        response = auth_client.post(CHANGE_PASSWORD, {"current_password": PASSWORD, "new_password": self.NEW})

        assert response.status_code == 200
        user.refresh_from_db()
        assert user.check_password(self.NEW)

    def test_wrong_current_password_is_rejected(self, auth_client, user):
        response = auth_client.post(CHANGE_PASSWORD, {"current_password": "wrong-one-1", "new_password": self.NEW})

        assert response.status_code == 400
        user.refresh_from_db()
        assert user.check_password(PASSWORD)

    def test_weak_new_password_is_rejected(self, auth_client):
        response = auth_client.post(CHANGE_PASSWORD, {"current_password": PASSWORD, "new_password": "123"})

        assert response.status_code == 400

    def test_changing_password_ends_current_refresh_session(self, auth_client):
        token = auth_client.cookies[settings.REFRESH_COOKIE_NAME].value

        auth_client.post(CHANGE_PASSWORD, {"current_password": PASSWORD, "new_password": self.NEW})

        auth_client.cookies[settings.REFRESH_COOKIE_NAME] = token
        assert auth_client.post(REFRESH).status_code == 401

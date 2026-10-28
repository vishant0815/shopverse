import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from accounts.models import User

PASSWORD = "Str0ng-Passw0rd!"


@pytest.fixture(autouse=True)
def fast_hashing_and_clean_cache(settings):
    # Argon2 is deliberately slow; tests don't need that.
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def make_user(db):
    def _make_user(email="alice@example.com", password=PASSWORD, **extra):
        extra.setdefault("first_name", "Alice")
        return User.objects.create_user(email=email, password=password, **extra)

    return _make_user


@pytest.fixture
def user(make_user):
    return make_user()


@pytest.fixture
def auth_client(api_client, user):
    response = api_client.post("/api/v1/auth/login/", {"email": user.email, "password": PASSWORD})
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    return api_client

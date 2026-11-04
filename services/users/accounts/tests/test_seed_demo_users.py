import io

import pytest
from django.core.management import CommandError, call_command

from accounts.management.commands.seed_demo_users import DEMO_SELLER_ID
from accounts.models import User

pytestmark = pytest.mark.django_db
PASSWORD = "Demo-Passw0rd-1234"


def seed(monkeypatch, password=PASSWORD):
    monkeypatch.setenv("DEMO_USER_PASSWORD", password)
    call_command("seed_demo_users", stdout=io.StringIO())


def test_creates_seller_and_admin(monkeypatch):
    seed(monkeypatch)

    seller = User.objects.get(email="seller@shopverse.dev")
    admin = User.objects.get(email="admin@shopverse.dev")
    assert seller.role == "seller" and seller.id == DEMO_SELLER_ID
    assert admin.role == "admin" and admin.is_staff
    assert seller.check_password(PASSWORD) and admin.check_password(PASSWORD)


def test_running_again_keeps_accounts_and_updates_password(monkeypatch):
    seed(monkeypatch)
    seed(monkeypatch, password="An0ther-Demo-Pass")

    assert User.objects.filter(email__in=["seller@shopverse.dev", "admin@shopverse.dev"]).count() == 2
    assert User.objects.get(email="seller@shopverse.dev").check_password("An0ther-Demo-Pass")


@pytest.mark.parametrize("password", ["", "change-me", "12345678"])
def test_refuses_missing_placeholder_or_weak_password(monkeypatch, password):
    with pytest.raises(CommandError):
        seed(monkeypatch, password)
    assert not User.objects.exists()


def test_demo_seller_can_log_in(monkeypatch, api_client):
    seed(monkeypatch)
    response = api_client.post("/api/v1/auth/login/", {"email": "seller@shopverse.dev", "password": PASSWORD})

    assert response.status_code == 200
    assert response.data["user"]["role"] == "seller"

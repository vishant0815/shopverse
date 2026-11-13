import importlib

import pytest
from django.apps import apps as global_apps
from django.core.management import call_command
import io

from accounts.models import SellerProfile, User
from accounts.sellers import InvalidTransition, change_status, create_seller_profile, ensure_approved_shop
from messaging.models import OutboxMessage

from .conftest import PASSWORD

REGISTER = "/api/v1/auth/register/"
LOGIN = "/api/v1/auth/login/"
SELLER_ME = "/api/v1/sellers/me/"
ADMIN_SELLERS = "/api/v1/admin/sellers/"

pytestmark = pytest.mark.django_db


def login(api_client, user):
    response = api_client.post(LOGIN, {"email": user.email, "password": PASSWORD})
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    return api_client


@pytest.fixture
def seller(make_user):
    user = make_user(email="sam@example.com", first_name="Sam", role="seller")
    create_seller_profile(user, "Sam's Shop")
    return user


@pytest.fixture
def admin(make_user):
    return make_user(email="ada@example.com", first_name="Ada", role="admin", is_staff=True)


def events_for(seller_id):
    return [row.payload["data"]["status"] for row in OutboxMessage.objects.filter(key=str(seller_id)).order_by("seq")]


class TestRegisteringASeller:
    def test_seller_starts_pending_and_is_announced(self, api_client):
        response = api_client.post(REGISTER, {
            "email": "new@example.com", "password": PASSWORD, "first_name": "New",
            "role": "seller", "shop_name": "  New Shop  ",
        })

        assert response.status_code == 201
        profile = SellerProfile.objects.get(user__email="new@example.com")
        assert profile.status == "pending" and profile.shop_name == "New Shop"
        assert events_for(profile.user_id) == ["pending"]

    def test_seller_needs_a_shop_name(self, api_client):
        response = api_client.post(REGISTER, {
            "email": "new@example.com", "password": PASSWORD, "first_name": "New", "role": "seller", "shop_name": "  ",
        })

        assert response.status_code == 400
        assert "shop_name" in response.data
        assert not User.objects.filter(email="new@example.com").exists()

    def test_customer_gets_no_shop(self, api_client):
        api_client.post(REGISTER, {"email": "buyer@example.com", "password": PASSWORD, "first_name": "Buy"})

        assert not SellerProfile.objects.filter(user__email="buyer@example.com").exists()


class TestSellerOwnShop:
    def test_seller_reads_and_updates_own_shop(self, api_client, seller):
        login(api_client, seller)

        assert api_client.get(SELLER_ME).data["shop_name"] == "Sam's Shop"
        response = api_client.patch(SELLER_ME, {"shop_name": "Sam's Better Shop", "description": "Oak furniture"})

        assert response.status_code == 200
        assert response.data["shop_name"] == "Sam's Better Shop"
        assert SellerProfile.objects.get(user=seller).description == "Oak furniture"

    def test_seller_cannot_change_their_own_status(self, api_client, seller):
        login(api_client, seller)
        api_client.patch(SELLER_ME, {"status": "approved"})

        assert SellerProfile.objects.get(user=seller).status == "pending"

    def test_customer_has_no_shop_endpoint(self, api_client, make_user):
        login(api_client, make_user(email="buyer@example.com"))

        assert api_client.get(SELLER_ME).status_code == 403

    def test_seller_without_a_shop_gets_404(self, api_client, make_user):
        login(api_client, make_user(email="orphan@example.com", role="seller"))

        assert api_client.get(SELLER_ME).status_code == 404


class TestAdminSellers:
    def test_only_admins_can_list_sellers(self, api_client, seller, make_user):
        login(api_client, seller)
        assert api_client.get(ADMIN_SELLERS).status_code == 403

        login(api_client, make_user(email="buyer@example.com"))
        assert api_client.get(ADMIN_SELLERS).status_code == 403

    def test_admin_lists_and_filters_by_status(self, api_client, admin, seller, make_user):
        other = make_user(email="other@example.com", role="seller")
        create_seller_profile(other, "Other Shop")
        change_status(SellerProfile.objects.get(user=other), "approved")
        login(api_client, admin)

        everyone = api_client.get(ADMIN_SELLERS).data["results"]
        pending = api_client.get(ADMIN_SELLERS, {"status": "pending"}).data["results"]

        assert {row["email"] for row in everyone} == {"sam@example.com", "other@example.com"}
        assert [row["email"] for row in pending] == ["sam@example.com"]
        assert pending[0]["seller_id"] == str(seller.id)

    def test_admin_approves_a_pending_seller(self, api_client, admin, seller):
        login(api_client, admin)

        response = api_client.post(f"{ADMIN_SELLERS}{seller.id}/approve/")

        assert response.status_code == 200
        assert response.data["status"] == "approved"
        assert SellerProfile.objects.get(user=seller).status == "approved"
        assert events_for(seller.id) == ["pending", "approved"]

    def test_admin_suspends_then_reinstates(self, api_client, admin, seller):
        login(api_client, admin)
        api_client.post(f"{ADMIN_SELLERS}{seller.id}/approve/")

        assert api_client.post(f"{ADMIN_SELLERS}{seller.id}/suspend/").data["status"] == "suspended"
        assert api_client.post(f"{ADMIN_SELLERS}{seller.id}/approve/").data["status"] == "approved"
        assert events_for(seller.id) == ["pending", "approved", "suspended", "approved"]

    def test_moves_that_make_no_sense_are_refused(self, api_client, admin, seller):
        login(api_client, admin)

        # Pending can't be suspended, and approving twice is refused.
        assert api_client.post(f"{ADMIN_SELLERS}{seller.id}/suspend/").status_code == 409
        api_client.post(f"{ADMIN_SELLERS}{seller.id}/approve/")
        assert api_client.post(f"{ADMIN_SELLERS}{seller.id}/approve/").status_code == 409

        # The refused moves announced nothing.
        assert events_for(seller.id) == ["pending", "approved"]

    def test_unknown_or_malformed_seller_is_404(self, api_client, admin):
        login(api_client, admin)

        assert api_client.post(f"{ADMIN_SELLERS}{'0' * 8}-0000-4000-8000-000000000000/approve/").status_code == 404
        assert api_client.post(f"{ADMIN_SELLERS}not-a-uuid/approve/").status_code == 404


class TestStatusChanges:
    def test_each_change_is_one_outbox_message_with_the_full_envelope(self, seller):
        profile = SellerProfile.objects.get(user=seller)
        change_status(profile, "approved")

        message = OutboxMessage.objects.filter(key=str(seller.id)).order_by("seq").last()
        assert message.topic == "users.events"
        assert message.type == "SellerStatusChanged"
        assert message.payload["source"] == "users"
        assert message.payload["data"] == {"seller_id": str(seller.id), "status": "approved"}
        assert message.payload["id"] == str(message.message_id)

    def test_refused_change_writes_nothing(self, seller):
        profile = SellerProfile.objects.get(user=seller)
        before = OutboxMessage.objects.count()

        with pytest.raises(InvalidTransition):
            change_status(profile, "suspended")

        assert OutboxMessage.objects.count() == before
        assert SellerProfile.objects.get(user=seller).status == "pending"


class TestBackfillMigration:
    def test_existing_sellers_become_approved_and_are_announced(self, make_user):
        old_seller = make_user(email="old@example.com", first_name="Old", role="seller")
        make_user(email="buyer@example.com")  # customers are left alone
        migration = importlib.import_module("accounts.migrations.0003_backfill_seller_profiles")

        migration.backfill(global_apps, None)

        profile = SellerProfile.objects.get(user=old_seller)
        assert profile.status == "approved" and profile.shop_name == "Old's shop"
        assert events_for(old_seller.id) == ["approved"]
        assert not SellerProfile.objects.filter(user__email="buyer@example.com").exists()

    def test_running_it_twice_changes_nothing(self, make_user):
        make_user(email="old@example.com", first_name="Old", role="seller")
        migration = importlib.import_module("accounts.migrations.0003_backfill_seller_profiles")

        migration.backfill(global_apps, None)
        migration.backfill(global_apps, None)

        assert SellerProfile.objects.count() == 1
        assert OutboxMessage.objects.filter(type="SellerStatusChanged").count() == 1


class TestEnsureApprovedShop:
    def test_only_announces_when_something_changes(self, make_user):
        user = make_user(email="demo@example.com", role="seller")

        ensure_approved_shop(user, "Demo Shop")
        ensure_approved_shop(user, "Demo Shop")

        assert SellerProfile.objects.get(user=user).status == "approved"
        assert events_for(user.id) == ["approved"]

    def test_demo_seed_creates_an_approved_seller_shop(self, monkeypatch):
        monkeypatch.setenv("DEMO_USER_PASSWORD", "Demo-Passw0rd-1234")
        call_command("seed_demo_users", stdout=io.StringIO())

        seller = User.objects.get(email="seller@shopverse.dev")
        assert SellerProfile.objects.get(user=seller).status == "approved"
        assert events_for(seller.id) == ["approved"]

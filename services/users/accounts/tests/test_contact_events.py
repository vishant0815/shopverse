"""Customers' contact details are announced for notifications: on signup, and when the
name or email changes. Saves that change neither announce nothing."""

import importlib

import pytest
from django.apps import apps
from django.utils import timezone

from accounts.contact import CONTACT_CHANGED, REGISTERED
from messaging.models import OutboxMessage

PROFILE = "/api/v1/users/me/"
SIGNUP = "/api/v1/auth/register/"


def contact_messages(type_=None):
    rows = OutboxMessage.objects.filter(topic="users.events").order_by("seq")
    if type_:
        rows = rows.filter(type=type_)
    return list(rows)


@pytest.fixture
def clear_outbox(db):
    OutboxMessage.objects.all().delete()


class TestSignup:
    def test_signup_announces_the_new_customer(self, api_client, clear_outbox):
        response = api_client.post(SIGNUP, {
            "email": "New.Customer@Example.com",
            "password": "Str0ng-Passw0rd!",
            "first_name": "Nia",
            "last_name": "Khan",
        }, format="json")

        assert response.status_code == 201
        [message] = contact_messages(REGISTERED)
        assert message.key == message.payload["data"]["user_id"]
        assert message.payload["type"] == REGISTERED
        assert message.payload["data"] == {
            "user_id": message.key,
            "email": "new.customer@example.com",
            "first_name": "Nia",
            "last_name": "Khan",
        }

    def test_creating_a_user_in_code_is_announced_too(self, make_user, clear_outbox):
        user = make_user(email="admin-made@example.com", first_name="Ada")

        [message] = contact_messages(REGISTERED)
        assert message.key == str(user.id)
        assert message.payload["data"]["email"] == "admin-made@example.com"


class TestChanges:
    def test_renaming_through_the_profile_announces_the_change(self, auth_client, user, clear_outbox):
        response = auth_client.patch(PROFILE, {"first_name": "Alicia"}, format="json")

        assert response.status_code == 200
        [message] = contact_messages(CONTACT_CHANGED)
        assert message.key == str(user.id)
        assert message.payload["data"]["first_name"] == "Alicia"

    def test_an_email_change_made_in_admin_is_announced(self, user, clear_outbox):
        user.email = "Moved@Example.com"
        user.save()

        [message] = contact_messages(CONTACT_CHANGED)
        assert message.payload["data"]["email"] == "moved@example.com"

    def test_saving_without_a_contact_change_announces_nothing(self, user, clear_outbox):
        user.phone = "07700900123"
        user.save()
        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])

        assert contact_messages() == []

    def test_resending_the_same_name_announces_nothing(self, auth_client, user, clear_outbox):
        response = auth_client.patch(PROFILE, {"first_name": "Alice"}, format="json")

        assert response.status_code == 200
        assert contact_messages() == []


class TestBackfill:
    def test_every_existing_customer_gets_a_registered_message(self, make_user):
        first = make_user(email="one@example.com")
        second = make_user(email="two@example.com", first_name="Two")
        OutboxMessage.objects.all().delete()

        migration = importlib.import_module("accounts.migrations.0004_backfill_user_contacts")
        migration.backfill(apps, None)

        messages = contact_messages(REGISTERED)
        assert sorted(m.key for m in messages) == sorted([str(first.id), str(second.id)])
        assert {m.payload["data"]["email"] for m in messages} == {"one@example.com", "two@example.com"}

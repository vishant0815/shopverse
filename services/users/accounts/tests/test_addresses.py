import pytest
from django.db import IntegrityError

from accounts.models import Address

from .conftest import PASSWORD

ADDRESSES = "/api/v1/addresses/"

pytestmark = pytest.mark.django_db


def address_payload(**overrides):
    data = {
        "full_name": "Alice Smith",
        "phone": "+447700900123",
        "line1": "1 High Street",
        "city": "London",
        "postcode": "e1 6an",
    }
    data.update(overrides)
    return data


def detail(address_id):
    return f"{ADDRESSES}{address_id}/"


def test_create_address_normalises_fields(auth_client):
    response = auth_client.post(ADDRESSES, address_payload(country="gb"))

    assert response.status_code == 201
    assert response.data["postcode"] == "E1 6AN"
    assert response.data["country"] == "GB"


def test_first_address_becomes_default(auth_client):
    response = auth_client.post(ADDRESSES, address_payload())

    assert response.data["is_default"] is True


def test_new_default_unsets_previous_default(auth_client, user):
    first = auth_client.post(ADDRESSES, address_payload()).data
    second = auth_client.post(ADDRESSES, address_payload(line1="2 Low Road", is_default=True)).data

    assert Address.objects.get(id=first["id"]).is_default is False
    assert Address.objects.get(id=second["id"]).is_default is True
    assert user.addresses.filter(is_default=True).count() == 1


def test_deleting_default_promotes_another_address(auth_client, user):
    first = auth_client.post(ADDRESSES, address_payload()).data
    second = auth_client.post(ADDRESSES, address_payload(line1="2 Low Road")).data

    assert auth_client.delete(detail(first["id"])).status_code == 204
    assert Address.objects.get(id=second["id"]).is_default is True


def test_database_enforces_single_default(user):
    Address.objects.create(user=user, **address_payload(), is_default=True)
    with pytest.raises(IntegrityError):
        # bulk_create skips save(), so this goes straight to the database constraint.
        Address.objects.bulk_create([Address(user=user, **address_payload(), is_default=True)])


def test_list_only_returns_own_addresses(auth_client, make_user):
    other = make_user(email="mallory@example.com")
    Address.objects.create(user=other, **address_payload(line1="Mallory's house"))
    auth_client.post(ADDRESSES, address_payload())

    response = auth_client.get(ADDRESSES)

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["line1"] == "1 High Street"


class TestOwnership:
    """A user must never read, change or delete another user's address."""

    @pytest.fixture
    def others_address(self, make_user):
        other = make_user(email="mallory@example.com")
        return Address.objects.create(user=other, **address_payload(line1="Mallory's house"))

    def test_cannot_read(self, auth_client, others_address):
        assert auth_client.get(detail(others_address.id)).status_code == 404

    def test_cannot_update(self, auth_client, others_address):
        response = auth_client.patch(detail(others_address.id), {"line1": "Hacked"})

        assert response.status_code == 404
        others_address.refresh_from_db()
        assert others_address.line1 == "Mallory's house"

    def test_cannot_delete(self, auth_client, others_address):
        assert auth_client.delete(detail(others_address.id)).status_code == 404
        assert Address.objects.filter(id=others_address.id).exists()

    def test_cannot_assign_address_to_another_user(self, auth_client, user, others_address):
        response = auth_client.post(ADDRESSES, address_payload(user=str(others_address.user_id)))

        assert response.status_code == 201
        assert Address.objects.get(id=response.data["id"]).user == user


def test_addresses_require_login(api_client):
    assert api_client.get(ADDRESSES).status_code == 401


def test_invalid_country_code_is_rejected(auth_client):
    assert auth_client.post(ADDRESSES, address_payload(country="UK1")).status_code == 400

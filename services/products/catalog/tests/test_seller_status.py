"""Seller approvals from the users service: applied from the message, and enforced on writes."""

import json
import uuid

import pytest

from catalog.handlers import HANDLERS
from catalog.models import SellerStatus
from catalog.permissions import seller_status
from messaging.kafka import process
from messaging.models import ProcessedMessage

SELLER_PRODUCTS = "/api/v1/seller/products/"

pytestmark = pytest.mark.django_db


def status_message(seller_id, status, message_id=None):
    return json.dumps({
        "id": str(message_id or uuid.uuid4()),
        "type": "SellerStatusChanged",
        "source": "users",
        "occurred_at": "2026-11-13T10:00:00.000Z",
        "key": str(seller_id),
        "data": {"seller_id": str(seller_id), "status": status},
    }).encode()


def announce(seller_id, status):
    process(HANDLERS, "users.events", status_message(seller_id, status))


def product_payload():
    return {
        "name": "Nova X1", "brand": "Nova", "description": "A phone", "category": "phones", "status": "active",
        "variants": [{"sku": "nova-x1-blk", "colour": "Black", "size": "128GB", "price": "399.00"}],
        "images": [],
    }


class TestAppliesMessages:
    def test_a_status_message_sets_the_sellers_status(self, client_as):
        seller = client_as("seller")
        announce(seller.user_id, "approved")

        assert seller_status(seller.user_id) == "approved"

    def test_a_later_message_replaces_the_status(self, client_as):
        seller = client_as("seller")
        announce(seller.user_id, "approved")
        announce(seller.user_id, "suspended")

        assert seller_status(seller.user_id) == "suspended"

    def test_a_redelivered_message_is_applied_once(self, client_as):
        seller = client_as("seller")
        message = status_message(seller.user_id, "approved")

        assert process(HANDLERS, "users.events", message) == "handled"
        assert process(HANDLERS, "users.events", message) == "duplicate"
        assert ProcessedMessage.objects.count() == 1

    def test_an_unknown_status_is_refused_rather_than_guessed(self, client_as):
        seller = client_as("seller")
        with pytest.raises(ValueError):
            process(HANDLERS, "users.events", status_message(seller.user_id, "banned"))

        assert not SellerStatus.objects.filter(seller_id=uuid.UUID(seller.user_id)).exists()

    def test_other_message_types_are_ignored(self, client_as):
        message = json.dumps({"id": str(uuid.uuid4()), "type": "SomethingElse", "source": "x",
                              "occurred_at": "2026-11-13T10:00:00.000Z", "key": "k", "data": {}}).encode()

        assert process(HANDLERS, "users.events", message) == "ignored"


class TestEnforcesOnWrites:
    def test_a_seller_with_no_status_cannot_create(self, client_as, categories):
        seller = client_as("seller")

        response = seller.post(SELLER_PRODUCTS, product_payload(), format="json")

        assert response.status_code == 403
        assert "waiting for approval" in response.data["detail"]

    def test_a_pending_seller_cannot_create(self, client_as, categories):
        seller = client_as("seller")
        announce(seller.user_id, "pending")

        response = seller.post(SELLER_PRODUCTS, product_payload(), format="json")

        assert response.status_code == 403
        assert "waiting for approval" in response.data["detail"]

    def test_a_suspended_seller_cannot_change_products(self, client_as, categories):
        seller = client_as("seller")
        announce(seller.user_id, "approved")
        created = seller.post(SELLER_PRODUCTS, product_payload(), format="json")
        assert created.status_code == 201

        announce(seller.user_id, "suspended")
        response = seller.patch(f"{SELLER_PRODUCTS}{created.data['id']}/", {"name": "Changed"}, format="json")

        assert response.status_code == 403
        assert "suspended" in response.data["detail"]

    def test_a_suspended_seller_can_still_read_their_products(self, client_as, categories):
        seller = client_as("seller")
        announce(seller.user_id, "approved")
        seller.post(SELLER_PRODUCTS, product_payload(), format="json")
        announce(seller.user_id, "suspended")

        assert seller.get(SELLER_PRODUCTS).status_code == 200

    def test_reinstating_a_seller_restores_writes(self, client_as, categories):
        seller = client_as("seller")
        announce(seller.user_id, "suspended")
        assert seller.post(SELLER_PRODUCTS, product_payload(), format="json").status_code == 403

        announce(seller.user_id, "approved")

        assert seller.post(SELLER_PRODUCTS, product_payload(), format="json").status_code == 201

    def test_admins_can_write_without_a_seller_status(self, admin, categories):
        assert admin.post(SELLER_PRODUCTS, product_payload(), format="json").status_code == 201

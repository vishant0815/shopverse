"""Seller approvals from the users service: applied from the message, and enforced on writes."""

import json
import uuid

import pytest

from catalog.handlers import HANDLERS
from catalog.models import Product, ProductVariant, SellerStatus
from catalog.permissions import seller_status
from messaging.kafka import process
from messaging.models import OutboxMessage, ProcessedMessage

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


PUBLIC_PRODUCTS = "/api/v1/products/"
LOOKUP = "/api/v1/variants/lookup/"


def listed_in_latest_announcement(product_id):
    message = (OutboxMessage.objects.filter(topic="catalog.products", type="ProductUpserted")
               .order_by("seq"))
    latest = [m for m in message if m.payload["data"]["product_id"] == str(product_id)][-1]
    return latest.payload["data"]["listed"]


class TestSuspendedShopsAreHidden:
    def create_listed_product(self, seller):
        announce(seller.user_id, "approved")
        created = seller.post(SELLER_PRODUCTS, product_payload(), format="json")
        assert created.status_code == 201
        product = Product.objects.get(pk=created.data["id"])
        return product, ProductVariant.objects.get(product=product)

    def test_shoppers_stop_seeing_a_suspended_shops_products(self, client_as, categories, anon):
        seller = client_as("seller")
        product, variant = self.create_listed_product(seller)
        assert product.slug in [p["slug"] for p in anon.get(PUBLIC_PRODUCTS).data["results"]]

        announce(seller.user_id, "suspended")

        assert product.slug not in [p["slug"] for p in anon.get(PUBLIC_PRODUCTS).data["results"]]
        assert anon.get(f"{PUBLIC_PRODUCTS}{product.slug}/").status_code == 404
        assert anon.get(f"{LOOKUP}?ids={variant.id}").data["results"] == []

    def test_reinstating_a_shop_brings_its_products_back(self, client_as, categories, anon):
        seller = client_as("seller")
        product, variant = self.create_listed_product(seller)
        announce(seller.user_id, "suspended")

        announce(seller.user_id, "approved")

        assert product.slug in [p["slug"] for p in anon.get(PUBLIC_PRODUCTS).data["results"]]
        assert anon.get(f"{LOOKUP}?ids={variant.id}").data["results"][0]["variant_id"] == str(variant.id)

    def test_suspension_republishes_the_product_as_unlisted(self, client_as, categories):
        seller = client_as("seller")
        product, _ = self.create_listed_product(seller)
        assert listed_in_latest_announcement(product.id) is True

        announce(seller.user_id, "suspended")
        assert listed_in_latest_announcement(product.id) is False

        announce(seller.user_id, "approved")
        assert listed_in_latest_announcement(product.id) is True

    def test_the_seller_still_sees_their_own_products_while_suspended(self, client_as, categories):
        seller = client_as("seller")
        product, _ = self.create_listed_product(seller)
        announce(seller.user_id, "suspended")

        ids = [p["id"] for p in seller.get(SELLER_PRODUCTS).data["results"]]

        assert str(product.id) in ids

    def test_a_shop_without_a_status_is_not_listed(self, client_as, categories, anon):
        seller = client_as("seller")
        product = Product.objects.create(
            seller_id=uuid.UUID(seller.user_id), name="Unknown seller", brand="X", description="",
            category=categories["phones"], status=Product.Status.ACTIVE,
        )

        assert product.slug not in [p["slug"] for p in anon.get(PUBLIC_PRODUCTS).data["results"]]

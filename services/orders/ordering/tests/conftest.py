import uuid
from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from ordering import catalog


def make_client(role="customer", user_id=None):
    token = AccessToken()
    token["user_id"] = str(user_id or uuid.uuid4())
    token["role"] = role
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    client.user_id = token["user_id"]
    return client


@pytest.fixture
def customer(db):
    return make_client("customer")


@pytest.fixture
def other_customer(db):
    return make_client("customer")


@pytest.fixture
def seller(db):
    return make_client("seller")


@pytest.fixture
def admin(db):
    return make_client("admin")


@pytest.fixture
def anon(db):
    return APIClient()


class FakeCatalogue:
    """Stands in for the product service so tests control prices and availability."""

    def __init__(self):
        self.variants = {}
        self.down = False
        self.calls = 0

    def add(self, price="10.00", seller_id=None, name="Test Product", **extra):
        variant_id = str(uuid.uuid4())
        self.variants[variant_id] = {
            "variant_id": variant_id,
            "sku": f"SKU-{variant_id[:6].upper()}",
            "colour": extra.get("colour", "Black"),
            "size": extra.get("size", "M"),
            "price": Decimal(price),
            "compare_at_price": None,
            "product_id": str(uuid.uuid4()),
            "product_name": name,
            "product_slug": name.lower().replace(" ", "-"),
            "seller_id": str(seller_id or uuid.uuid4()),
            "thumbnail": "https://example.com/img.jpg",
        }
        return variant_id

    def remove(self, variant_id):
        self.variants.pop(variant_id)

    def set_price(self, variant_id, price):
        self.variants[variant_id]["price"] = Decimal(price)

    def lookup(self, variant_ids):
        self.calls += 1
        if self.down:
            raise catalog.CatalogUnavailable
        return {str(v): dict(self.variants[str(v)]) for v in variant_ids if str(v) in self.variants}


@pytest.fixture
def catalogue(monkeypatch):
    fake = FakeCatalogue()
    monkeypatch.setattr(catalog, "lookup_variants", fake.lookup)
    return fake


ADDRESS = {
    "full_name": "Alice Smith",
    "phone": "+447700900123",
    "line1": "1 High Street",
    "city": "London",
    "postcode": "e1 6an",
}


@pytest.fixture
def address():
    return dict(ADDRESS)


@pytest.fixture
def place_order(catalogue, address):
    """Add items to a customer's cart and check out. Returns the response."""

    def _place(client, items=(("10.00", 1),), key=None, seller_id=None):
        for price, quantity in items:
            variant_id = catalogue.add(price=price, seller_id=seller_id)
            client.post("/api/v1/cart/items/", {"variant_id": variant_id, "quantity": quantity}, format="json")
        headers = {"HTTP_IDEMPOTENCY_KEY": key} if key else {}
        return client.post("/api/v1/checkout/", {"shipping_address": address}, format="json", **headers)

    return _place

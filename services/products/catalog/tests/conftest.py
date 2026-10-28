import uuid
from decimal import Decimal

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from catalog.models import Category, Product, ProductImage, ProductVariant


@pytest.fixture(autouse=True)
def clean_cache():
    cache.clear()
    yield
    cache.clear()


def make_token(role, user_id=None):
    """Build a token the same way the users service does: user_id and role claims."""
    token = AccessToken()
    token["user_id"] = str(user_id or uuid.uuid4())
    token["role"] = role
    return token


@pytest.fixture
def client_as():
    """client_as("seller") -> an APIClient authenticated as a new seller.
    The client's .user_id attribute holds the id inside its token."""

    def _client(role, user_id=None):
        token = make_token(role, user_id)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        client.user_id = token["user_id"]
        return client

    return _client


@pytest.fixture
def anon():
    return APIClient()


@pytest.fixture
def seller(client_as):
    return client_as("seller")


@pytest.fixture
def other_seller(client_as):
    return client_as("seller")


@pytest.fixture
def admin(client_as):
    return client_as("admin")


@pytest.fixture
def customer(client_as):
    return client_as("customer")


@pytest.fixture
def categories(db):
    electronics = Category.objects.create(name="Electronics")
    phones = Category.objects.create(name="Phones", parent=electronics)
    fashion = Category.objects.create(name="Fashion")
    return {"electronics": electronics, "phones": phones, "fashion": fashion}


@pytest.fixture
def make_product(categories):
    def _make(seller_id=None, name="Test Phone", category="phones", brand="Acme",
              status=Product.Status.ACTIVE, variants=(("Black", "M", "100.00"),), image=True):
        product = Product.objects.create(
            seller_id=seller_id or uuid.uuid4(),
            category=categories[category],
            name=name,
            brand=brand,
            status=status,
        )
        for colour, size, price in variants:
            ProductVariant.objects.create(
                product=product, sku=f"SKU-{uuid.uuid4().hex[:8]}", colour=colour, size=size, price=Decimal(price)
            )
        if image:
            ProductImage.objects.create(product=product, url="https://example.com/img.jpg")
        return product

    return _make

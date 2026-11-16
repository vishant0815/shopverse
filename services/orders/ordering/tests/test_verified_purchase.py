import uuid
from decimal import Decimal

import pytest

from ordering.models import Order, OrderItem

URL = "/api/v1/internal/verified-purchase/"

pytestmark = pytest.mark.django_db


def bought(user_id, product_id, status=Order.Status.DELIVERED):
    """An order for one unit of the product, in the given state."""
    order = Order.objects.create(
        user_id=user_id,
        status=status,
        subtotal=Decimal("20.00"),
        discount_amount=Decimal("0.00"),
        total=Decimal("20.00"),
        shipping_address={"line1": "1 High Street"},
    )
    OrderItem.objects.create(
        order=order,
        variant_id=uuid.uuid4(),
        product_id=product_id,
        seller_id=uuid.uuid4(),
        sku="LAMP-1",
        product_name="Desk lamp",
        product_slug="desk-lamp",
        unit_price=Decimal("20.00"),
        quantity=1,
        line_total=Decimal("20.00"),
    )
    return order


def ask(client, user_id, product_id):
    return client.get(URL, data={"user_id": str(user_id), "product_id": str(product_id)})


def test_a_delivered_order_verifies_the_purchase(anon):
    user, product = uuid.uuid4(), uuid.uuid4()
    bought(user, product)
    response = ask(anon, user, product)
    assert response.status_code == 200
    assert response.json() == {"verified": True}


@pytest.mark.parametrize("status", [Order.Status.PAID, Order.Status.SHIPPED, Order.Status.CANCELLED])
def test_an_order_not_yet_delivered_does_not_verify(anon, status):
    user, product = uuid.uuid4(), uuid.uuid4()
    bought(user, product, status=status)
    assert ask(anon, user, product).json() == {"verified": False}


def test_another_customers_purchase_does_not_verify(anon):
    product = uuid.uuid4()
    bought(uuid.uuid4(), product)
    assert ask(anon, uuid.uuid4(), product).json() == {"verified": False}


def test_a_purchase_of_another_product_does_not_verify(anon):
    user = uuid.uuid4()
    bought(user, uuid.uuid4())
    assert ask(anon, user, uuid.uuid4()).json() == {"verified": False}


def test_bad_ids_are_refused(anon):
    response = anon.get(URL, data={"user_id": "not-a-uuid", "product_id": "also-not"})
    assert response.status_code == 400

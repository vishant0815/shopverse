import uuid
from decimal import Decimal

import pytest

from ordering.models import Order, OrderItem

CART_ITEMS = "/api/v1/cart/items/"
CART = "/api/v1/cart/"
CHECKOUT = "/api/v1/checkout/"
SOLD = "/api/v1/flash-sales/sold/"

pytestmark = pytest.mark.django_db


def put_on_sale(catalogue, variant_id, *, sale_price="80.00", cap=None, regular="100.00"):
    """Give a catalogue variant a running flash sale, shaped the way the products service sends it."""
    item_id = str(uuid.uuid4())
    catalogue.set_price(variant_id, sale_price)
    catalogue.variants[variant_id]["regular_price"] = regular
    catalogue.variants[variant_id]["flash_sale"] = {
        "item_id": item_id,
        "sale_id": str(uuid.uuid4()),
        "name": "Weekend trainers",
        "sale_price": sale_price,
        "quantity_cap": cap,
        "ends_at": "2026-11-16T21:00:00+00:00",
    }
    return item_id


def add_to_cart(client, variant_id, quantity):
    response = client.post(CART_ITEMS, {"variant_id": variant_id, "quantity": quantity}, format="json")
    assert response.status_code in (200, 201)


def checkout(client, address):
    return client.post(CHECKOUT, {"shipping_address": address}, format="json")


def test_checkout_charges_the_sale_price_and_records_the_sale_item(customer, catalogue, address):
    variant_id = catalogue.add(price="100.00")
    item_id = put_on_sale(catalogue, variant_id, cap=10)
    add_to_cart(customer, variant_id, 2)

    response = checkout(customer, address)

    assert response.status_code == 201
    line = OrderItem.objects.get(order__number=response.data["number"])
    assert line.unit_price == Decimal("80.00")
    assert str(line.flash_sale_item_id) == item_id


def test_a_capped_sale_refuses_more_than_its_cap(customer, catalogue, address):
    variant_id = catalogue.add(price="100.00")
    put_on_sale(catalogue, variant_id, cap=3)
    add_to_cart(customer, variant_id, 4)

    response = checkout(customer, address)

    assert response.status_code == 409
    assert response.data["code"] == "flash_sale_sold_out"
    assert response.data["remaining"] == 3
    assert not Order.objects.exists()


def test_units_already_bought_count_against_the_cap(customer, other_customer, catalogue, address):
    variant_id = catalogue.add(price="100.00")
    put_on_sale(catalogue, variant_id, cap=3)
    add_to_cart(other_customer, variant_id, 2)
    assert checkout(other_customer, address).status_code == 201

    add_to_cart(customer, variant_id, 2)
    response = checkout(customer, address)

    assert response.status_code == 409
    assert response.data["remaining"] == 1


def test_cancelled_orders_give_their_units_back(customer, catalogue, address):
    variant_id = catalogue.add(price="100.00")
    put_on_sale(catalogue, variant_id, cap=2)
    add_to_cart(customer, variant_id, 2)
    first = checkout(customer, address)
    assert first.status_code == 201
    Order.objects.filter(number=first.data["number"]).update(status=Order.Status.CANCELLED)

    add_to_cart(customer, variant_id, 2)

    assert checkout(customer, address).status_code == 201


def test_an_uncapped_sale_has_no_limit(customer, catalogue, address):
    variant_id = catalogue.add(price="100.00")
    put_on_sale(catalogue, variant_id, cap=None)
    add_to_cart(customer, variant_id, 5)

    assert checkout(customer, address).status_code == 201


def test_the_sold_count_reflects_live_orders(customer, anon, catalogue, address):
    variant_id = catalogue.add(price="100.00")
    item_id = put_on_sale(catalogue, variant_id, cap=10)
    add_to_cart(customer, variant_id, 3)
    assert checkout(customer, address).status_code == 201

    response = anon.get(SOLD, {"items": item_id})

    assert response.status_code == 200
    assert response.data["results"] == {item_id: 3}


def test_the_sold_count_rejects_ids_that_are_not_uuids(anon):
    assert anon.get(SOLD, {"items": "not-a-uuid"}).status_code == 400


def test_the_cart_shows_the_sale_and_the_regular_price(customer, catalogue):
    variant_id = catalogue.add(price="100.00")
    item_id = put_on_sale(catalogue, variant_id, cap=10)
    add_to_cart(customer, variant_id, 1)

    line = customer.get(CART).data["items"][0]

    assert line["unit_price"] == "80.00"
    assert line["regular_price"] == "100.00"
    assert line["flash_sale"]["item_id"] == item_id

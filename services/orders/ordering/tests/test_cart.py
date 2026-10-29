import pytest
from django.test import override_settings

CART = "/api/v1/cart/"
ITEMS = "/api/v1/cart/items/"

pytestmark = pytest.mark.django_db


def item_url(variant_id):
    return f"{ITEMS}{variant_id}/"


def add(client, variant_id, quantity=1):
    return client.post(ITEMS, {"variant_id": variant_id, "quantity": quantity}, format="json")


def test_cart_requires_login(anon):
    assert anon.get(CART).status_code == 401


def test_new_cart_is_empty(customer, catalogue):
    response = customer.get(CART)

    assert response.status_code == 200
    assert response.data["items"] == []
    assert response.data["total"] == "0.00"


def test_add_item_returns_cart_with_live_prices(customer, catalogue):
    variant_id = catalogue.add(price="12.50", name="Oxford Shirt")

    response = add(customer, variant_id, 2)

    assert response.status_code == 201
    line = response.data["items"][0]
    assert line["product_name"] == "Oxford Shirt"
    assert line["unit_price"] == "12.50"
    assert line["line_total"] == "25.00"
    assert response.data["subtotal"] == "25.00"


def test_client_cannot_set_the_price(customer, catalogue):
    variant_id = catalogue.add(price="100.00")

    response = customer.post(ITEMS, {"variant_id": variant_id, "quantity": 1, "price": "0.01"}, format="json")

    assert response.data["items"][0]["unit_price"] == "100.00"


def test_adding_same_item_again_increases_quantity(customer, catalogue):
    variant_id = catalogue.add()
    add(customer, variant_id, 2)

    response = add(customer, variant_id, 3)

    assert len(response.data["items"]) == 1
    assert response.data["items"][0]["quantity"] == 5


def test_cannot_add_unavailable_item(customer, catalogue):
    assert add(customer, "00000000-0000-4000-8000-000000000000").status_code == 404


def test_catalogue_down_when_adding_returns_503(customer, catalogue):
    variant_id = catalogue.add()
    catalogue.down = True

    assert add(customer, variant_id).status_code == 503


@pytest.mark.parametrize("quantity", [0, -1])
def test_quantity_must_be_positive(customer, catalogue, quantity):
    assert add(customer, catalogue.add(), quantity).status_code == 400


@override_settings(MAX_QUANTITY_PER_ITEM=5)
def test_quantity_per_item_is_capped_across_adds(customer, catalogue):
    variant_id = catalogue.add()
    add(customer, variant_id, 4)

    assert add(customer, variant_id, 2).status_code == 400
    assert customer.patch(item_url(variant_id), {"quantity": 6}, format="json").status_code == 400


@override_settings(MAX_CART_ITEMS=2)
def test_number_of_lines_is_capped(customer, catalogue):
    add(customer, catalogue.add())
    add(customer, catalogue.add())

    assert add(customer, catalogue.add()).status_code == 400


def test_update_and_remove_item(customer, catalogue):
    variant_id = catalogue.add(price="5.00")
    add(customer, variant_id)

    updated = customer.patch(item_url(variant_id), {"quantity": 3}, format="json")
    assert updated.data["subtotal"] == "15.00"

    removed = customer.delete(item_url(variant_id))
    assert removed.data["items"] == []


def test_clear_cart(customer, catalogue):
    add(customer, catalogue.add())
    add(customer, catalogue.add())

    assert customer.delete(CART).status_code == 204
    assert customer.get(CART).data["items"] == []


def test_carts_are_private(customer, other_customer, catalogue):
    variant_id = catalogue.add()
    add(customer, variant_id)

    assert other_customer.get(CART).data["items"] == []
    assert other_customer.delete(item_url(variant_id)).status_code == 404
    assert len(customer.get(CART).data["items"]) == 1


def test_items_that_become_unavailable_are_flagged(customer, catalogue):
    keep, gone = catalogue.add(price="10.00"), catalogue.add(price="99.00")
    add(customer, keep)
    add(customer, gone)
    catalogue.remove(gone)

    response = customer.get(CART)

    assert response.data["unavailable_variant_ids"] == [gone]
    assert response.data["subtotal"] == "10.00"


def test_cart_still_loads_when_catalogue_is_down(customer, catalogue):
    add(customer, catalogue.add())
    catalogue.down = True

    response = customer.get(CART)

    assert response.status_code == 200
    assert response.data["prices_available"] is False
    assert len(response.data["items"]) == 1


class TestShipping:
    def test_small_orders_pay_shipping(self, customer, catalogue):
        response = add(customer, catalogue.add(price="20.00"))

        assert response.data["shipping_fee"] == "4.99"
        assert response.data["total"] == "24.99"

    def test_free_shipping_at_threshold(self, customer, catalogue):
        response = add(customer, catalogue.add(price="25.00"), 2)

        assert response.data["shipping_fee"] == "0.00"
        assert response.data["total"] == "50.00"

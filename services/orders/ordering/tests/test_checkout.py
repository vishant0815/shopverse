import pytest

from ordering import checkout as checkout_module
from ordering.models import Cart, Order, OrderItem

CHECKOUT = "/api/v1/checkout/"
ITEMS = "/api/v1/cart/items/"

pytestmark = pytest.mark.django_db


def add(client, variant_id, quantity=1):
    return client.post(ITEMS, {"variant_id": variant_id, "quantity": quantity}, format="json")


def checkout(client, address, key=None, **extra):
    headers = {"HTTP_IDEMPOTENCY_KEY": key} if key else {}
    return client.post(CHECKOUT, {"shipping_address": address, **extra}, format="json", **headers)


def test_checkout_creates_order_with_snapshot_and_clears_cart(customer, catalogue, address):
    variant_id = catalogue.add(price="19.99", name="Linen Dress")
    add(customer, variant_id, 2)

    response = checkout(customer, address)

    assert response.status_code == 201
    data = response.data
    assert data["number"].startswith("SV-")
    assert data["status"] == "pending_payment"
    assert data["subtotal"] == "39.98"
    assert data["shipping_fee"] == "4.99"
    assert data["total"] == "44.97"
    assert data["shipping_address"]["postcode"] == "E1 6AN"
    assert data["items"][0]["product_name"] == "Linen Dress"
    assert data["items"][0]["unit_price"] == "19.99"
    assert data["history"][0]["to_status"] == "pending_payment"
    assert Cart.objects.get(user_id=customer.user_id).items.count() == 0


def test_order_keeps_old_price_after_catalogue_changes(customer, catalogue, address):
    variant_id = catalogue.add(price="10.00")
    add(customer, variant_id)
    number = checkout(customer, address).data["number"]

    catalogue.set_price(variant_id, "99.00")

    assert customer.get(f"/api/v1/orders/{number}/").data["items"][0]["unit_price"] == "10.00"


def test_order_records_each_items_seller(customer, catalogue, address):
    first, second = catalogue.add(), catalogue.add()
    add(customer, first)
    add(customer, second)

    order = Order.objects.get(number=checkout(customer, address).data["number"])

    expected = {catalogue.variants[first]["seller_id"], catalogue.variants[second]["seller_id"]}
    assert {str(s) for s in order.items.values_list("seller_id", flat=True)} == expected


def test_empty_cart_cannot_check_out(customer, catalogue, address):
    response = checkout(customer, address)

    assert response.status_code == 400
    assert response.data["code"] == "cart_empty"


def test_address_is_required_and_validated(customer, catalogue, address):
    add(customer, catalogue.add())

    assert customer.post(CHECKOUT, {}, format="json").status_code == 400
    assert checkout(customer, {**address, "country": "UK1"}).status_code == 400


def test_unavailable_item_blocks_checkout(customer, catalogue, address):
    gone = catalogue.add()
    add(customer, gone)
    catalogue.remove(gone)

    response = checkout(customer, address)

    assert response.status_code == 409
    assert response.data["code"] == "items_unavailable"
    assert response.data["unavailable_variant_ids"] == [gone]
    assert Order.objects.count() == 0


def test_catalogue_down_returns_503_and_keeps_cart(customer, catalogue, address):
    add(customer, catalogue.add())
    catalogue.down = True

    response = checkout(customer, address)

    assert response.status_code == 503
    assert Cart.objects.get(user_id=customer.user_id).items.count() == 1


class TestPriceProtection:
    def test_matching_expected_total_succeeds(self, customer, catalogue, address):
        add(customer, catalogue.add(price="60.00"))

        assert checkout(customer, address, expected_total="60.00").status_code == 201

    def test_price_change_since_viewing_is_caught(self, customer, catalogue, address):
        variant_id = catalogue.add(price="60.00")
        add(customer, variant_id)
        catalogue.set_price(variant_id, "75.00")

        response = checkout(customer, address, expected_total="60.00")

        assert response.status_code == 409
        assert response.data["code"] == "price_changed"
        assert response.data["actual_total"] == "75.00"
        assert Order.objects.count() == 0


class TestIdempotency:
    def test_same_key_returns_same_order(self, customer, catalogue, address):
        add(customer, catalogue.add())
        first = checkout(customer, address, key="click-123")

        # The cart is now empty, but the repeated request still gets the original order back.
        second = checkout(customer, address, key="click-123")

        assert first.status_code == 201
        assert second.status_code == 200
        assert second.data["number"] == first.data["number"]
        assert Order.objects.count() == 1

    def test_different_keys_create_different_orders(self, customer, catalogue, address):
        add(customer, catalogue.add())
        checkout(customer, address, key="a")
        add(customer, catalogue.add())

        assert checkout(customer, address, key="b").status_code == 201
        assert Order.objects.count() == 2

    def test_keys_are_scoped_per_user(self, customer, other_customer, catalogue, address):
        add(customer, catalogue.add())
        add(other_customer, catalogue.add())

        mine = checkout(customer, address, key="same-key")
        theirs = checkout(other_customer, address, key="same-key")

        assert theirs.status_code == 201
        assert theirs.data["number"] != mine.data["number"]

    def test_duplicate_waiting_on_the_lock_gets_the_winners_order(
        self, customer, catalogue, address, monkeypatch
    ):
        add(customer, catalogue.add())
        original_lookup = catalogue.lookup
        winner = {}

        def lookup_while_duplicate_wins(ids):
            # While this request fetches prices, an identical request finishes checkout.
            result = original_lookup(ids)
            winner["order"] = Order.objects.create(
                user_id=customer.user_id, subtotal=10, shipping_fee=0, total=10,
                shipping_address=address, idempotency_key="double-click",
            )
            Cart.objects.get(user_id=customer.user_id).items.all().delete()
            return result

        monkeypatch.setattr(checkout_module.catalog, "lookup_variants", lookup_while_duplicate_wins)

        response = checkout(customer, address, key="double-click")

        assert response.status_code == 200
        assert response.data["number"] == winner["order"].number
        assert Order.objects.count() == 1

    def test_overlong_key_is_rejected(self, customer, catalogue, address):
        add(customer, catalogue.add())

        assert checkout(customer, address, key="x" * 101).status_code == 400


def test_cart_changed_during_pricing_is_caught(customer, catalogue, address, monkeypatch):
    variant_id = catalogue.add()
    add(customer, variant_id)
    original_lookup = catalogue.lookup

    def lookup_while_cart_changes(ids):
        # Simulate the customer adding more in another tab while prices are being fetched.
        Cart.objects.get(user_id=customer.user_id).items.update(quantity=3)
        return original_lookup(ids)

    monkeypatch.setattr(checkout_module.catalog, "lookup_variants", lookup_while_cart_changes)

    response = checkout(customer, address)

    assert response.status_code == 409
    assert response.data["code"] == "cart_changed"
    assert Order.objects.count() == 0


def test_database_rejects_inconsistent_totals(customer, catalogue, address):
    from django.db import IntegrityError

    add(customer, catalogue.add())
    order = Order.objects.get(number=checkout(customer, address).data["number"])

    with pytest.raises(IntegrityError):
        Order.objects.filter(pk=order.pk).update(total=1)


def test_database_rejects_inconsistent_line_total(customer, catalogue, address):
    from django.db import IntegrityError

    add(customer, catalogue.add(price="10.00"), 2)
    checkout(customer, address)

    with pytest.raises(IntegrityError):
        OrderItem.objects.update(line_total=5)

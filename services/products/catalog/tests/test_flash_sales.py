from datetime import timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.core.management import call_command
from django.utils import timezone

from catalog import events
from catalog.models import FlashSale, FlashSaleItem

LOOKUP = "/api/v1/variants/lookup/"
ADMIN = "/api/v1/admin/flash-sales/"

pytestmark = pytest.mark.django_db


def ids_param(*ids):
    return {"ids": ",".join(str(i) for i in ids)}


def make_sale(variant, *, sale_price="80.00", cap=None, start=timedelta(hours=-1), end=timedelta(hours=1),
              active=True, name="Weekend"):
    """A sale running from `start` to `end` relative to now, holding one item for `variant`."""
    now = timezone.now()
    sale = FlashSale.objects.create(name=name, starts_at=now + start, ends_at=now + end, is_active=active)
    return FlashSaleItem.objects.create(sale=sale, variant=variant, sale_price=Decimal(sale_price), quantity_cap=cap)


def sale_payload(*items, start=timedelta(hours=-1), end=timedelta(hours=1)):
    now = timezone.now()
    return {
        "name": "Weekend trainers",
        "starts_at": (now + start).isoformat(),
        "ends_at": (now + end).isoformat(),
        "items": list(items),
    }


# Pricing at the variant lookup, which carts use ------------------------------------------------

def test_lookup_gives_the_sale_price_while_a_sale_runs(anon, make_product):
    variant = make_product(variants=[("Blue", "42", "100.00")]).variants.get()
    item = make_sale(variant, sale_price="80.00", cap=200)

    result = anon.get(LOOKUP, ids_param(variant.id)).data["results"][0]

    assert result["price"] == "80.00"
    assert result["regular_price"] == "100.00"
    assert result["flash_sale"]["item_id"] == str(item.id)
    assert result["flash_sale"]["sale_price"] == "80.00"
    assert result["flash_sale"]["quantity_cap"] == 200


@pytest.mark.parametrize("window", [
    {"start": timedelta(hours=1), "end": timedelta(hours=2)},     # not started yet
    {"start": timedelta(hours=-2), "end": timedelta(hours=-1)},   # already ended
])
def test_lookup_keeps_the_regular_price_outside_the_window(anon, make_product, window):
    variant = make_product(variants=[("Blue", "42", "100.00")]).variants.get()
    make_sale(variant, **window)

    result = anon.get(LOOKUP, ids_param(variant.id)).data["results"][0]

    assert result["price"] == "100.00"
    assert result["regular_price"] == "100.00"
    assert result["flash_sale"] is None


def test_lookup_ignores_a_switched_off_sale(anon, make_product):
    variant = make_product(variants=[("Blue", "42", "100.00")]).variants.get()
    make_sale(variant, active=False)

    result = anon.get(LOOKUP, ids_param(variant.id)).data["results"][0]

    assert result["price"] == "100.00"
    assert result["flash_sale"] is None


# Creating and switching sales (admin) -----------------------------------------------------------

def test_admin_creates_a_sale_with_items(admin, make_product, django_capture_on_commit_callbacks):
    product = make_product(variants=[("Blue", "42", "100.00"), ("Grey", "43", "100.00")])
    blue, grey = product.variants.order_by("sku")
    payload = sale_payload(
        {"variant": str(blue.id), "sale_price": "80.00", "quantity_cap": 200},
        {"variant": str(grey.id), "sale_price": "75.00", "quantity_cap": None},
    )

    with mock.patch.object(events, "announce_product") as announce, django_capture_on_commit_callbacks(execute=True):
        response = admin.post(ADMIN, payload, format="json")

    assert response.status_code == 201, response.data
    sale = FlashSale.objects.get()
    assert sale.is_active is True
    assert sorted(sale.items.values_list("sale_price", flat=True)) == [Decimal("75.00"), Decimal("80.00")]
    # The product's search document changes when the sale starts, so it is announced.
    announce.assert_called_with(product.id)


def test_customer_cannot_create_a_sale(customer, make_product):
    variant = make_product().variants.get()

    response = customer.post(ADMIN, sale_payload({"variant": str(variant.id), "sale_price": "80.00"}), format="json")

    assert response.status_code == 403
    assert not FlashSale.objects.exists()


def test_sale_price_must_be_below_the_regular_price(admin, make_product):
    variant = make_product(variants=[("Blue", "42", "100.00")]).variants.get()

    response = admin.post(ADMIN, sale_payload({"variant": str(variant.id), "sale_price": "100.00"}), format="json")

    assert response.status_code == 400
    assert "below the regular price" in str(response.data["items"])


def test_sale_must_end_after_it_starts(admin, make_product):
    variant = make_product().variants.get()
    payload = sale_payload({"variant": str(variant.id), "sale_price": "80.00"},
                           start=timedelta(hours=1), end=timedelta(minutes=30))

    response = admin.post(ADMIN, payload, format="json")

    assert response.status_code == 400
    assert "after the start" in str(response.data["ends_at"])


def test_a_variant_cannot_be_in_two_overlapping_sales(admin, make_product):
    variant = make_product().variants.get()
    make_sale(variant, start=timedelta(hours=-1), end=timedelta(hours=1))

    payload = sale_payload({"variant": str(variant.id), "sale_price": "70.00"},
                           start=timedelta(minutes=30), end=timedelta(hours=3))
    response = admin.post(ADMIN, payload, format="json")

    assert response.status_code == 400
    assert "overlaps" in str(response.data["items"])


def test_a_variant_can_be_in_back_to_back_sales(admin, make_product):
    variant = make_product().variants.get()
    make_sale(variant, start=timedelta(hours=-3), end=timedelta(hours=-1))

    payload = sale_payload({"variant": str(variant.id), "sale_price": "70.00"},
                           start=timedelta(hours=-1), end=timedelta(hours=2))
    response = admin.post(ADMIN, payload, format="json")

    assert response.status_code == 201, response.data


def test_switching_a_sale_off_restores_the_regular_price(admin, anon, make_product):
    variant = make_product(variants=[("Blue", "42", "100.00")]).variants.get()
    item = make_sale(variant)

    response = admin.patch(f"{ADMIN}{item.sale_id}/", {"is_active": False}, format="json")

    assert response.status_code == 200
    result = anon.get(LOOKUP, ids_param(variant.id)).data["results"][0]
    assert result["price"] == "100.00"
    assert result["flash_sale"] is None


# Search and the product page -----------------------------------------------------------------

def test_search_document_shows_the_sale_price(make_product):
    product = make_product(variants=[("Blue", "42", "100.00")])
    make_sale(product.variants.get(), sale_price="80.00")

    document = events.product_document(product, revision=1)

    assert document["price_min"] == "80.00"
    variant = document["variants"][0]
    assert variant["price"] == "80.00"
    assert variant["regular_price"] == "100.00"
    assert variant["flash_sale"]["sale_price"] == "80.00"


def test_variant_detail_reports_its_running_sale(make_product):
    from catalog.serializers import VariantSerializer

    variant = make_product(variants=[("Blue", "42", "100.00")]).variants.get()
    make_sale(variant, sale_price="80.00")

    data = VariantSerializer(variant).data

    assert data["price"] == "100.00"
    assert data["flash_sale"]["sale_price"] == "80.00"


# The refresh command, which moves search prices when a sale starts or ends ---------------------

def test_refresh_announces_products_whose_sale_just_started(make_product):
    just_started = make_product(name="Just started").variants.get()
    make_sale(just_started, start=timedelta(seconds=-30), end=timedelta(hours=1))
    long_running = make_product(name="Long running").variants.get()
    make_sale(long_running, start=timedelta(hours=-1), end=timedelta(hours=1))

    with mock.patch("catalog.management.commands.refresh_flash_sale_listings.events.announce_product") as announce:
        call_command("refresh_flash_sale_listings")

    announce.assert_called_once_with(just_started.product_id)


def test_refresh_announces_products_whose_sale_just_ended(make_product):
    variant = make_product().variants.get()
    make_sale(variant, start=timedelta(hours=-2), end=timedelta(seconds=-45))

    with mock.patch("catalog.management.commands.refresh_flash_sale_listings.events.announce_product") as announce:
        call_command("refresh_flash_sale_listings")

    announce.assert_called_once_with(variant.product_id)

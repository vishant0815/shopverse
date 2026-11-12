"""Catalogue events: every variant change is announced on catalog.variants."""

import pytest
from django.core.management import call_command

from catalog.models import Product, ProductVariant
from messaging.models import OutboxMessage

from .test_seller import SELLER_PRODUCTS, detail, product_payload

pytestmark = pytest.mark.django_db


def events(*types):
    return [(m.type, m.payload["data"]) for m in OutboxMessage.objects.order_by("seq")
            if not types or m.type in types]


def test_a_new_product_announces_each_variant_with_its_seller(seller, categories):
    response = seller.post(SELLER_PRODUCTS, product_payload(), format="json")

    announced = events()
    assert [kind for kind, _ in announced] == ["VariantUpserted", "VariantUpserted"]
    assert {data["sku"] for _, data in announced} == {"NOVA-X1-BLK", "NOVA-X1-BLU"}
    for _, data in announced:
        assert data["seller_id"] == seller.user_id
        assert data["product_id"] == response.data["id"]
        assert data["active"] is True
    assert {m.topic for m in OutboxMessage.objects.all()} == {"catalog.variants"}


def test_adding_editing_and_removing_a_variant_are_announced(seller, make_product):
    product = make_product(seller_id=seller.user_id)
    OutboxMessage.objects.all().delete()
    url = f"{detail(product.id)}variants/"

    added = seller.post(url, {"sku": "NEW-1", "colour": "Red", "price": "5.00"}, format="json").data
    seller.patch(f"{url}{added['id']}/", {"price": "6.00"}, format="json")
    seller.delete(f"{url}{added['id']}/")

    kinds = [(kind, data["variant_id"], data["active"]) for kind, data in events()]
    assert kinds == [
        ("VariantUpserted", added["id"], True),
        ("VariantUpserted", added["id"], True),
        ("VariantUpserted", added["id"], False),  # removing a variant only deactivates it
    ]


def test_deleting_a_product_for_good_announces_its_variants_are_gone(make_product):
    product = make_product(variants=(("Black", "M", "10.00"), ("Blue", "M", "10.00")))
    ids = {str(v.id) for v in product.variants.all()}
    OutboxMessage.objects.all().delete()

    product.delete()

    assert {data["variant_id"] for _, data in events("VariantRemoved")} == ids


def test_a_rejected_request_announces_nothing(seller, categories):
    response = seller.post(SELLER_PRODUCTS, product_payload(variants=[{"sku": "X", "price": "-1"}]), format="json")

    assert response.status_code == 400
    assert events() == []


def test_if_the_event_cannot_be_written_the_change_is_not_saved_either(seller, categories, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr("catalog.events.enqueue", broken)

    with pytest.raises(RuntimeError):
        seller.post(SELLER_PRODUCTS, product_payload(), format="json")

    assert not Product.objects.exists()
    assert not ProductVariant.objects.exists()


def test_the_backfill_announces_every_variant_once(make_product):
    make_product(variants=(("Black", "M", "10.00"), ("Blue", "M", "10.00")))
    make_product(name="Other", variants=(("Red", "S", "5.00"),))
    OutboxMessage.objects.all().delete()

    call_command("publish_catalog", "--once")
    call_command("publish_catalog", "--once")  # already done: nothing more

    assert len(events("VariantUpserted")) == 3

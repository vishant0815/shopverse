"""Catalogue events: every change reaches the outbox, with the topic and content consumers need."""

import pytest
from django.core.management import call_command

from catalog.models import Category, Product, ProductImage, ProductVariant
from messaging.models import OutboxMessage

from .test_seller import SELLER_PRODUCTS, detail, product_payload

pytestmark = pytest.mark.django_db

VARIANTS = "catalog.variants"
PRODUCTS = "catalog.products"


def announced(topic, *types):
    """(type, data) for every message on the topic, in the order they were written."""
    rows = OutboxMessage.objects.filter(topic=topic).order_by("seq")
    return [(m.type, m.payload["data"]) for m in rows if not types or m.type in types]


def states(product_id):
    """Every ProductUpserted for one product, oldest first."""
    return [data for _, data in announced(PRODUCTS, "ProductUpserted") if data["product_id"] == str(product_id)]


def latest(product_id):
    return states(product_id)[-1]


# Inventory's view: variants ------------------------------------------------------------

def test_a_new_product_announces_each_variant_with_its_seller(seller, categories):
    response = seller.post(SELLER_PRODUCTS, product_payload(), format="json")

    variant_events = announced(VARIANTS)
    assert [kind for kind, _ in variant_events] == ["VariantUpserted", "VariantUpserted"]
    assert {data["sku"] for _, data in variant_events} == {"NOVA-X1-BLK", "NOVA-X1-BLU"}
    for _, data in variant_events:
        assert data["seller_id"] == seller.user_id
        assert data["product_id"] == response.data["id"]
        assert data["active"] is True


def test_adding_editing_and_removing_a_variant_are_announced(seller, make_product):
    product = make_product(seller_id=seller.user_id)
    OutboxMessage.objects.all().delete()
    url = f"{detail(product.id)}variants/"

    added = seller.post(url, {"sku": "NEW-1", "colour": "Red", "size": "M", "price": "5.00"}, format="json").data
    seller.patch(f"{url}{added['id']}/", {"price": "6.00"}, format="json")
    seller.delete(f"{url}{added['id']}/")

    # Removing a variant through the seller API deactivates it; the row is only deleted with its product.
    announcements = [(kind, data["variant_id"], data["active"]) for kind, data in announced(VARIANTS)]
    assert announcements == [
        ("VariantUpserted", added["id"], True),
        ("VariantUpserted", added["id"], True),
        ("VariantUpserted", added["id"], False),
    ]


def test_deleting_a_product_for_good_announces_its_variants_are_gone(make_product):
    product = make_product(variants=(("Black", "M", "10.00"), ("Blue", "M", "10.00")))
    ids = {str(v.id) for v in product.variants.all()}
    OutboxMessage.objects.all().delete()

    product.delete()

    assert {data["variant_id"] for _, data in announced(VARIANTS, "VariantRemoved")} == ids


# Search's view: products ---------------------------------------------------------------

def test_a_product_is_announced_with_its_whole_listing(make_product):
    product = make_product(variants=(("Black", "M", "100.00"), ("Blue", "L", "80.00")))

    doc = latest(product.id)

    assert doc["listed"] is True
    assert doc["name"] == "Test Phone"
    assert doc["brand"] == "Acme"
    assert doc["category"]["slug"] == "phones"
    assert doc["category_slugs"] == ["phones", "electronics"]
    assert doc["category_names"] == ["Phones", "Electronics"]
    assert doc["colours"] == ["Black", "Blue"]
    assert doc["sizes"] == ["L", "M"]
    assert (doc["price_min"], doc["price_max"]) == ("80.00", "100.00")
    assert doc["image_url"] == "https://example.com/img.jpg"
    assert len(doc["variants"]) == 2


def test_a_new_product_from_the_seller_api_is_announced(seller, categories):
    response = seller.post(SELLER_PRODUCTS, product_payload(), format="json")

    doc = latest(response.data["id"])
    assert doc["name"] == "Nova X1"
    assert doc["listed"] is True


def test_every_announcement_gets_the_next_revision(make_product):
    product = make_product(variants=(("Black", "M", "10.00"),))  # product, variant and image saves

    revisions = [doc["revision"] for doc in states(product.id)]

    assert revisions == list(range(1, len(revisions) + 1))
    assert len(revisions) == 3


def test_a_draft_is_not_listed_until_it_is_published(make_product):
    product = make_product(status=Product.Status.DRAFT)
    assert latest(product.id)["listed"] is False

    product.status = Product.Status.ACTIVE
    product.save()

    assert latest(product.id)["listed"] is True


def test_hiding_a_category_hides_its_products_and_subcategories(make_product, categories):
    product = make_product(category="phones")

    categories["electronics"].is_active = False
    categories["electronics"].save()

    assert latest(product.id)["listed"] is False


def test_renaming_a_parent_category_updates_the_products_beneath_it(make_product, categories):
    product = make_product(category="phones")

    categories["electronics"].name = "Tech"
    categories["electronics"].save()

    assert latest(product.id)["category_names"] == ["Phones", "Tech"]


def test_price_range_and_facets_follow_only_the_active_variants(make_product):
    product = make_product(variants=(("Black", "M", "100.00"), ("Blue", "M", "80.00")))
    cheapest = ProductVariant.objects.get(product=product, colour="Blue")

    cheapest.is_active = False
    cheapest.save()
    doc = latest(product.id)
    assert (doc["price_min"], doc["price_max"]) == ("100.00", "100.00")
    assert doc["colours"] == ["Black"]

    cheapest.is_active = True
    cheapest.price = "60.00"
    cheapest.save()
    assert latest(product.id)["price_min"] == "60.00"


def test_an_image_change_updates_the_listing_image(make_product):
    product = make_product(image=False)

    ProductImage.objects.create(product=product, url="https://example.com/new.jpg")

    assert latest(product.id)["image_url"] == "https://example.com/new.jpg"


def test_deleting_a_product_announces_its_removal_last(make_product):
    product = make_product(variants=(("Black", "M", "10.00"),))
    product_id = str(product.id)

    product.delete()

    product_events = [(kind, data) for kind, data in announced(PRODUCTS) if data["product_id"] == product_id]
    assert product_events[-1] == ("ProductRemoved", {"product_id": product_id})


def test_a_rejected_request_announces_nothing(seller, categories):
    response = seller.post(SELLER_PRODUCTS, product_payload(variants=[{"sku": "X", "price": "-1"}]), format="json")

    assert response.status_code == 400
    assert announced(VARIANTS) == []
    assert announced(PRODUCTS) == []


def test_if_the_event_cannot_be_written_the_change_is_not_saved_either(seller, categories, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr("catalog.events.enqueue", broken)

    with pytest.raises(RuntimeError):
        seller.post(SELLER_PRODUCTS, product_payload(), format="json")

    assert not Product.objects.exists()
    assert not ProductVariant.objects.exists()


def test_the_backfill_announces_every_variant_and_product_once(make_product):
    make_product(variants=(("Black", "M", "10.00"), ("Blue", "M", "10.00")))
    make_product(name="Other", variants=(("Red", "S", "5.00"),))
    OutboxMessage.objects.all().delete()

    call_command("publish_catalog", "--once")
    first = OutboxMessage.objects.count()
    call_command("publish_catalog", "--once")  # already done: nothing more

    assert len(announced(VARIANTS, "VariantUpserted")) == 3
    assert len(announced(PRODUCTS, "ProductUpserted")) >= 2
    assert OutboxMessage.objects.count() == first

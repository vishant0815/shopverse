import uuid

import pytest

from catalog.models import Product

LOOKUP = "/api/v1/variants/lookup/"

pytestmark = pytest.mark.django_db


def ids_param(*ids):
    return {"ids": ",".join(str(i) for i in ids)}


def test_returns_live_price_and_product_details(anon, make_product):
    product = make_product(name="Nova", variants=[("Black", "M", "49.99")])
    variant = product.variants.get()

    response = anon.get(LOOKUP, ids_param(variant.id))

    assert response.status_code == 200
    item = response.data["results"][0]
    assert item["variant_id"] == str(variant.id)
    assert item["price"] == "49.99"
    assert item["product_name"] == "Nova"
    assert item["seller_id"] == str(product.seller_id)
    assert item["thumbnail"] == "https://example.com/img.jpg"


def test_unavailable_variants_are_left_out(anon, make_product):
    live = make_product(name="Live").variants.get()
    draft = make_product(name="Draft", status=Product.Status.DRAFT).variants.get()
    inactive = make_product(name="Inactive").variants.get()
    inactive.is_active = False
    inactive.save()

    response = anon.get(LOOKUP, ids_param(live.id, draft.id, inactive.id, uuid.uuid4()))

    assert [r["variant_id"] for r in response.data["results"]] == [str(live.id)]


@pytest.mark.parametrize("params", [{}, {"ids": ""}, {"ids": "not-a-uuid"}])
def test_bad_input_is_rejected(anon, params):
    assert anon.get(LOOKUP, params).status_code == 400


def test_too_many_ids_are_rejected(anon):
    assert anon.get(LOOKUP, ids_param(*[uuid.uuid4() for _ in range(101)])).status_code == 400

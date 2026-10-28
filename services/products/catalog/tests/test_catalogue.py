"""Public storefront: browsing, filtering, searching and sorting."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from catalog.models import Product

PRODUCTS = "/api/v1/products/"

pytestmark = pytest.mark.django_db


def names(response):
    return [p["name"] for p in response.data["results"]]


def test_anyone_can_browse_without_logging_in(anon, make_product):
    make_product()
    response = anon.get(PRODUCTS)

    assert response.status_code == 200
    assert response.data["count"] == 1


def test_only_published_products_are_listed(anon, make_product):
    make_product(name="Live")
    make_product(name="Draft", status=Product.Status.DRAFT)
    make_product(name="Archived", status=Product.Status.ARCHIVED)

    assert names(anon.get(PRODUCTS)) == ["Live"]


def test_products_in_inactive_categories_are_hidden(anon, make_product, categories):
    make_product()
    categories["phones"].is_active = False
    categories["phones"].save()

    assert anon.get(PRODUCTS).data["count"] == 0


def test_list_shows_lowest_active_variant_price_and_thumbnail(anon, make_product):
    make_product(variants=[("Black", "S", "120.00"), ("Blue", "S", "99.50")])
    item = anon.get(PRODUCTS).data["results"][0]

    assert item["min_price"] == "99.50"
    assert item["thumbnail"] == "https://example.com/img.jpg"


def test_detail_by_slug_includes_variants_and_images(anon, make_product):
    product = make_product(variants=[("Black", "S", "10.00"), ("Blue", "S", "12.00")])
    response = anon.get(f"{PRODUCTS}{product.slug}/")

    assert response.status_code == 200
    assert len(response.data["variants"]) == 2
    assert len(response.data["images"]) == 1


def test_draft_detail_is_not_public(anon, make_product):
    product = make_product(status=Product.Status.DRAFT)

    assert anon.get(f"{PRODUCTS}{product.slug}/").status_code == 404


def test_inactive_variants_are_hidden_from_customers(anon, make_product):
    product = make_product(variants=[("Black", "S", "10.00"), ("Blue", "S", "12.00")])
    product.variants.filter(colour="Blue").update(is_active=False)

    response = anon.get(f"{PRODUCTS}{product.slug}/")
    assert [v["colour"] for v in response.data["variants"]] == ["Black"]


def test_listing_uses_a_fixed_number_of_queries(anon, make_product):
    make_product(name="One")
    with CaptureQueriesContext(connection) as few:
        anon.get(PRODUCTS)

    for i in range(10):
        make_product(name=f"Extra {i}")
    with CaptureQueriesContext(connection) as many:
        anon.get(PRODUCTS)

    # No N+1: eleven products cost the same number of queries as one.
    assert len(many) == len(few)


class TestFilters:
    def test_category_includes_subcategories(self, anon, make_product):
        make_product(name="Phone", category="phones")
        make_product(name="Shirt", category="fashion")

        assert names(anon.get(PRODUCTS, {"category": "electronics"})) == ["Phone"]

    def test_unknown_category_returns_nothing(self, anon, make_product):
        make_product()
        assert anon.get(PRODUCTS, {"category": "nope"}).data["count"] == 0

    def test_price_range(self, anon, make_product):
        make_product(name="Cheap", variants=[("Black", "S", "10.00")])
        make_product(name="Mid", variants=[("Black", "S", "50.00")])
        make_product(name="Pricey", variants=[("Black", "S", "500.00")])

        response = anon.get(PRODUCTS, {"min_price": 20, "max_price": 100})
        assert names(response) == ["Mid"]

    def test_brand_accepts_comma_separated_list_case_insensitively(self, anon, make_product):
        make_product(name="A", brand="Acme")
        make_product(name="B", brand="Bolt")
        make_product(name="C", brand="Core")

        assert sorted(names(anon.get(PRODUCTS, {"brand": "acme,BOLT"}))) == ["A", "B"]

    def test_colour_and_size_match_variants_without_duplicates(self, anon, make_product):
        make_product(name="Shirt", variants=[("Blue", "M", "20.00"), ("Blue", "L", "20.00"), ("Red", "M", "20.00")])
        make_product(name="Hat", variants=[("Red", "M", "5.00")])

        assert names(anon.get(PRODUCTS, {"colour": "blue"})) == ["Shirt"]
        assert sorted(names(anon.get(PRODUCTS, {"size": "M"}))) == ["Hat", "Shirt"]

    def test_search_matches_name_brand_and_description(self, anon, make_product):
        make_product(name="Nova Phone", brand="Nova")
        make_product(name="Laptop", brand="Aero")

        assert names(anon.get(PRODUCTS, {"search": "nova"})) == ["Nova Phone"]

    def test_sort_by_price(self, anon, make_product):
        make_product(name="Mid", variants=[("Black", "S", "50.00")])
        make_product(name="Cheap", variants=[("Black", "S", "10.00")])
        make_product(name="Pricey", variants=[("Black", "S", "500.00")])

        assert names(anon.get(PRODUCTS, {"ordering": "min_price"})) == ["Cheap", "Mid", "Pricey"]
        assert names(anon.get(PRODUCTS, {"ordering": "-min_price"})) == ["Pricey", "Mid", "Cheap"]

    def test_pagination(self, anon, make_product):
        for i in range(5):
            make_product(name=f"P{i}")

        response = anon.get(PRODUCTS, {"page_size": 2})
        assert response.data["count"] == 5
        assert len(response.data["results"]) == 2
        assert response.data["next"] is not None

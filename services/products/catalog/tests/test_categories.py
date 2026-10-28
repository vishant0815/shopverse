import pytest
from django.core.cache import cache

from catalog.models import Category
from catalog.signals import CATEGORY_TREE_CACHE_KEY

CATEGORIES = "/api/v1/categories/"
TREE = "/api/v1/categories/tree/"

pytestmark = pytest.mark.django_db


def test_tree_is_nested(anon, categories):
    tree = anon.get(TREE).data
    electronics = next(node for node in tree if node["slug"] == "electronics")

    assert [child["slug"] for child in electronics["children"]] == ["phones"]


def test_tree_is_cached_and_invalidated_on_change(anon, categories, django_assert_num_queries):
    anon.get(TREE)
    assert cache.get(CATEGORY_TREE_CACHE_KEY) is not None

    with django_assert_num_queries(0):
        anon.get(TREE)

    Category.objects.create(name="Books")
    assert cache.get(CATEGORY_TREE_CACHE_KEY) is None
    assert any(node["slug"] == "books" for node in anon.get(TREE).data)


def test_inactive_categories_are_hidden_from_public(anon, categories):
    categories["fashion"].is_active = False
    categories["fashion"].save()

    slugs = [c["slug"] for c in anon.get(CATEGORIES).data]
    assert "fashion" not in slugs


def test_only_admin_can_create(customer, seller, admin, categories):
    payload = {"name": "Books"}

    assert customer.post(CATEGORIES, payload).status_code == 403
    assert seller.post(CATEGORIES, payload).status_code == 403

    response = admin.post(CATEGORIES, {"name": "Smart Watches", "parent": "electronics"}, format="json")
    assert response.status_code == 201
    assert response.data["slug"] == "smart-watches"
    assert response.data["parent"] == "electronics"


def test_category_cannot_become_its_own_ancestor(admin, categories):
    response = admin.patch(f"{CATEGORIES}electronics/", {"parent": "phones"}, format="json")

    assert response.status_code == 400


def test_delete_deactivates(admin, categories):
    assert admin.delete(f"{CATEGORIES}fashion/").status_code == 204
    categories["fashion"].refresh_from_db()
    assert categories["fashion"].is_active is False

"""Sellers managing products: roles, ownership and validation."""

import uuid

import pytest

from catalog.models import Product, ProductVariant

SELLER_PRODUCTS = "/api/v1/seller/products/"

pytestmark = pytest.mark.django_db


def product_payload(**overrides):
    data = {
        "name": "Nova X1",
        "brand": "Nova",
        "description": "A phone",
        "category": "phones",
        "status": "active",
        "variants": [
            {"sku": "nova-x1-blk", "colour": "Black", "size": "128GB", "price": "399.00", "compare_at_price": "449.00"},
            {"sku": "NOVA-X1-BLU", "colour": "Blue", "size": "128GB", "price": "399.00"},
        ],
        "images": [{"url": "https://example.com/nova.jpg", "alt_text": "Nova X1"}],
    }
    data.update(overrides)
    return data


def detail(product_id):
    return f"{SELLER_PRODUCTS}{product_id}/"


class TestRoles:
    def test_anonymous_cannot_create(self, anon, categories):
        assert anon.post(SELLER_PRODUCTS, product_payload(), format="json").status_code == 401

    def test_customer_cannot_create(self, customer, categories):
        assert customer.post(SELLER_PRODUCTS, product_payload(), format="json").status_code == 403

    def test_forged_token_is_rejected(self, anon, categories):
        anon.credentials(HTTP_AUTHORIZATION="Bearer eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYWRtaW4ifQ.fake")
        assert anon.post(SELLER_PRODUCTS, product_payload(), format="json").status_code == 401


class TestCreate:
    def test_seller_creates_product_with_variants_and_images(self, seller, categories):
        response = seller.post(SELLER_PRODUCTS, product_payload(), format="json")

        assert response.status_code == 201
        product = Product.objects.get(id=response.data["id"])
        assert str(product.seller_id) == seller.user_id
        assert product.variants.count() == 2
        assert product.images.count() == 1
        assert response.data["slug"].startswith("nova-x1-")
        assert {v["sku"] for v in response.data["variants"]} == {"NOVA-X1-BLK", "NOVA-X1-BLU"}

    def test_seller_id_comes_from_token_not_body(self, seller, categories):
        response = seller.post(SELLER_PRODUCTS, product_payload(seller_id=str(uuid.uuid4())), format="json")

        assert str(Product.objects.get(id=response.data["id"]).seller_id) == seller.user_id

    def test_discount_is_calculated(self, seller, categories):
        response = seller.post(SELLER_PRODUCTS, product_payload(), format="json")
        black = next(v for v in response.data["variants"] if v["colour"] == "Black")

        assert black["discount_percent"] == 11

    def test_cannot_publish_without_variants(self, seller, categories):
        response = seller.post(SELLER_PRODUCTS, product_payload(variants=[]), format="json")

        assert response.status_code == 400
        assert "status" in response.data

    def test_can_save_draft_without_variants(self, seller, categories):
        response = seller.post(SELLER_PRODUCTS, product_payload(variants=[], status="draft"), format="json")

        assert response.status_code == 201

    def test_compare_at_price_below_price_is_rejected(self, seller, categories):
        variants = [{"sku": "A1", "colour": "Black", "price": "100.00", "compare_at_price": "90.00"}]
        response = seller.post(SELLER_PRODUCTS, product_payload(variants=variants), format="json")

        assert response.status_code == 400

    @pytest.mark.parametrize("price", ["0", "-5.00"])
    def test_price_must_be_positive(self, seller, categories, price):
        variants = [{"sku": "A1", "colour": "Black", "price": price}]
        response = seller.post(SELLER_PRODUCTS, product_payload(variants=variants), format="json")

        assert response.status_code == 400

    def test_duplicate_sku_is_rejected(self, seller, categories, make_product):
        existing = make_product()
        sku = existing.variants.first().sku
        variants = [{"sku": sku, "colour": "Black", "price": "10.00"}]

        assert seller.post(SELLER_PRODUCTS, product_payload(variants=variants), format="json").status_code == 400

    def test_duplicate_variant_options_are_rejected(self, seller, categories):
        variants = [
            {"sku": "A1", "colour": "Black", "size": "M", "price": "10.00"},
            {"sku": "A2", "colour": "Black", "size": "M", "price": "12.00"},
        ]
        assert seller.post(SELLER_PRODUCTS, product_payload(variants=variants), format="json").status_code == 400

    def test_inactive_category_is_rejected(self, seller, categories):
        categories["phones"].is_active = False
        categories["phones"].save()

        assert seller.post(SELLER_PRODUCTS, product_payload(), format="json").status_code == 400


class TestOwnership:
    def test_seller_sees_only_own_products_including_drafts(self, seller, make_product):
        make_product(seller_id=seller.user_id, name="Mine", status=Product.Status.DRAFT)
        make_product(name="Someone else's")

        response = seller.get(SELLER_PRODUCTS)
        assert [p["name"] for p in response.data["results"]] == ["Mine"]

    def test_seller_cannot_read_update_or_delete_others_products(self, seller, make_product):
        theirs = make_product(name="Theirs")

        assert seller.get(detail(theirs.id)).status_code == 404
        assert seller.patch(detail(theirs.id), {"name": "Hacked"}, format="json").status_code == 404
        assert seller.delete(detail(theirs.id)).status_code == 404
        theirs.refresh_from_db()
        assert theirs.name == "Theirs"
        assert theirs.status == Product.Status.ACTIVE

    def test_seller_cannot_add_variants_to_others_products(self, seller, make_product):
        theirs = make_product()
        response = seller.post(f"{detail(theirs.id)}variants/", {"sku": "X1", "price": "1.00"}, format="json")

        assert response.status_code == 404
        assert theirs.variants.count() == 1

    def test_admin_can_manage_any_product(self, admin, make_product):
        product = make_product(name="Anyone's")

        response = admin.patch(detail(product.id), {"name": "Fixed by admin"}, format="json")
        assert response.status_code == 200
        product.refresh_from_db()
        assert product.name == "Fixed by admin"


class TestUpdateAndDelete:
    def test_update_core_fields(self, seller, make_product):
        product = make_product(seller_id=seller.user_id)
        response = seller.patch(detail(product.id), {"description": "Updated"}, format="json")

        assert response.status_code == 200
        assert response.data["description"] == "Updated"

    def test_cannot_change_variants_through_product_update(self, seller, make_product):
        product = make_product(seller_id=seller.user_id)
        response = seller.patch(detail(product.id), {"variants": []}, format="json")

        assert response.status_code == 400

    def test_delete_archives_instead_of_deleting(self, seller, make_product):
        product = make_product(seller_id=seller.user_id)

        assert seller.delete(detail(product.id)).status_code == 204
        product.refresh_from_db()
        assert product.status == Product.Status.ARCHIVED

    def test_cannot_publish_draft_with_no_active_variants(self, seller, make_product):
        product = make_product(seller_id=seller.user_id, status=Product.Status.DRAFT, variants=[])

        assert seller.patch(detail(product.id), {"status": "active"}, format="json").status_code == 400


class TestVariantsAndImages:
    def test_add_list_and_update_variants(self, seller, make_product):
        product = make_product(seller_id=seller.user_id)
        url = f"{detail(product.id)}variants/"

        created = seller.post(url, {"sku": "new-1", "colour": "Red", "size": "L", "price": "15.00"}, format="json")
        assert created.status_code == 201
        assert created.data["sku"] == "NEW-1"

        assert len(seller.get(url).data) == 2

        updated = seller.patch(f"{url}{created.data['id']}/", {"price": "12.50"}, format="json")
        assert updated.data["price"] == "12.50"

    def test_deleting_variant_deactivates_it(self, seller, make_product):
        product = make_product(seller_id=seller.user_id, variants=[("Black", "S", "1.00"), ("Blue", "S", "1.00")])
        variant = product.variants.first()

        assert seller.delete(f"{detail(product.id)}variants/{variant.id}/").status_code == 204
        variant.refresh_from_db()
        assert variant.is_active is False

    def test_deactivating_last_variant_unpublishes_product(self, seller, make_product):
        product = make_product(seller_id=seller.user_id)
        variant = product.variants.first()

        seller.patch(f"{detail(product.id)}variants/{variant.id}/", {"is_active": False}, format="json")

        product.refresh_from_db()
        assert product.status == Product.Status.DRAFT

    def test_add_image(self, seller, make_product):
        product = make_product(seller_id=seller.user_id, image=False)
        response = seller.post(f"{detail(product.id)}images/", {"url": "https://example.com/a.jpg"}, format="json")

        assert response.status_code == 201
        assert product.images.count() == 1

    def test_image_url_must_be_valid(self, seller, make_product):
        product = make_product(seller_id=seller.user_id)
        response = seller.post(f"{detail(product.id)}images/", {"url": "javascript:alert(1)"}, format="json")

        assert response.status_code == 400


def test_database_rejects_non_positive_price(make_product):
    from django.db import IntegrityError

    product = make_product()
    with pytest.raises(IntegrityError):
        ProductVariant.objects.filter(product=product).update(price=0)

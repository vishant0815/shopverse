import uuid
from decimal import Decimal
from unittest import mock

import httpx
import pytest

from catalog import events
from catalog import reviews as review_service
from catalog.models import Review

pytestmark = pytest.mark.django_db

GOOD = {"rating": 4, "title": "Solid lamp", "body": "Bright enough for reading and the arm holds its position well."}


def reviews_url(slug):
    return f"/api/v1/products/{slug}/reviews/"


def mine_url(slug):
    return f"/api/v1/products/{slug}/reviews/mine/"


def admin_url(review_id):
    return f"/api/v1/admin/reviews/{review_id}/"


@pytest.fixture
def lamp(make_product, seller):
    return make_product(seller_id=uuid.UUID(seller.user_id), name="Desk lamp")


@pytest.fixture
def orders(monkeypatch):
    """Stands in for the orders service. Set .verified to say whether purchases check out,
    or .unavailable to make the orders service unreachable."""

    class Answers:
        verified = True
        unavailable = False

    answers = Answers()

    def purchase_check(user_id, product_id):
        if answers.unavailable:
            raise review_service.PurchaseCheckUnavailable
        return answers.verified

    monkeypatch.setattr(review_service, "verified_purchase", purchase_check)
    return answers


def write_review(client, slug, **changes):
    return client.post(reviews_url(slug), {**GOOD, **changes}, format="json")


def test_summary_is_empty_before_any_review(anon, lamp):
    response = anon.get(reviews_url(lamp.slug))
    assert response.status_code == 200
    assert response.json() == {
        "summary": {"average": None, "count": 0, "distribution": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}},
        "results": [],
    }


def test_a_verified_buyer_can_review_and_the_rating_follows(customer, lamp, orders):
    response = write_review(customer, lamp.slug)
    assert response.status_code == 201
    assert response.json()["rating"] == 4
    lamp.refresh_from_db()
    assert lamp.rating_count == 1
    assert lamp.rating_average == Decimal("4.00")


def test_a_customer_who_has_not_bought_the_product_cannot_review(customer, lamp, orders):
    orders.verified = False
    response = write_review(customer, lamp.slug)
    assert response.status_code == 403
    assert response.json()["code"] == "not_verified_buyer"
    assert Review.objects.count() == 0


def test_signed_out_visitors_cannot_review(anon, lamp, orders):
    response = anon.post(reviews_url(lamp.slug), GOOD, format="json")
    assert response.status_code == 401
    assert Review.objects.count() == 0


def test_a_customer_gets_one_review_per_product(customer, lamp, orders):
    assert write_review(customer, lamp.slug).status_code == 201
    response = write_review(customer, lamp.slug, title="Second go")
    assert response.status_code == 409
    assert response.json()["code"] == "already_reviewed"
    assert Review.objects.count() == 1


@pytest.mark.parametrize("change", [
    {"rating": 6},
    {"rating": 0},
    {"body": "Too short."},
    {"title": "   "},
    {"title": "x" * 121},
])
def test_bad_input_is_refused(customer, lamp, orders, change):
    assert write_review(customer, lamp.slug, **change).status_code == 400
    assert Review.objects.count() == 0


def test_an_unreachable_orders_service_blocks_the_review(customer, lamp, orders):
    orders.unavailable = True
    response = write_review(customer, lamp.slug)
    assert response.status_code == 503
    assert response.json()["code"] == "verification_unavailable"
    assert Review.objects.count() == 0


def test_hiding_a_review_takes_it_off_the_page_and_out_of_the_rating(
    customer, client_as, admin, lamp, orders,
):
    write_review(customer, lamp.slug)
    second = client_as("customer")
    write_review(second, lamp.slug, rating=2)
    hidden = Review.objects.get(rating=2)

    response = admin.patch(admin_url(hidden.id), {"status": "hidden"}, format="json")
    assert response.status_code == 200
    lamp.refresh_from_db()
    assert lamp.rating_count == 1
    assert lamp.rating_average == Decimal("4.00")

    listed = admin.get("/api/v1/admin/reviews/", {"status": "hidden"}).json()["results"]
    assert [item["id"] for item in listed] == [str(hidden.id)]
    page = Review.objects.filter(status="visible").count()
    assert page == 1


def test_the_rating_average_rounds_half_up_to_two_places(client_as, lamp, orders):
    for rating in (5, 5, 4):
        write_review(client_as("customer"), lamp.slug, rating=rating)
    lamp.refresh_from_db()
    assert lamp.rating_average == Decimal("4.67")
    assert lamp.rating_count == 3


def test_mine_shows_the_customers_own_review_and_whether_they_may_write_one(customer, lamp, orders):
    assert customer.get(mine_url(lamp.slug)).json() == {"review": None, "verified": True}

    orders.verified = False
    assert customer.get(mine_url(lamp.slug)).json() == {"review": None, "verified": False}

    orders.verified = True
    write_review(customer, lamp.slug)
    orders.unavailable = True  # an existing review needs no purchase check
    body = customer.get(mine_url(lamp.slug)).json()
    assert body["verified"] is True
    assert body["review"]["rating"] == 4


def test_editing_your_review_updates_the_rating(customer, lamp, orders):
    write_review(customer, lamp.slug)
    response = customer.put(mine_url(lamp.slug), {**GOOD, "rating": 2}, format="json")
    assert response.status_code == 200
    lamp.refresh_from_db()
    assert lamp.rating_average == Decimal("2.00")


def test_editing_without_a_review_is_not_found(customer, lamp, orders):
    response = customer.put(mine_url(lamp.slug), GOOD, format="json")
    assert response.status_code == 404
    assert response.json()["code"] == "no_review"


def test_only_admins_can_moderate(customer, lamp, orders):
    write_review(customer, lamp.slug)
    review = Review.objects.get()
    assert customer.get("/api/v1/admin/reviews/").status_code == 403
    assert customer.patch(admin_url(review.id), {"status": "hidden"}, format="json").status_code == 403


def test_the_admin_list_filters_by_status(admin, customer, lamp, orders):
    write_review(customer, lamp.slug)
    review = Review.objects.get()
    admin.patch(admin_url(review.id), {"status": "hidden"}, format="json")
    assert len(admin.get("/api/v1/admin/reviews/", {"status": "visible"}).json()["results"]) == 0
    assert len(admin.get("/api/v1/admin/reviews/", {"status": "hidden"}).json()["results"]) == 1


def test_the_orders_service_is_asked_about_the_customer_and_product(monkeypatch, settings):
    settings.ORDERS_SERVICE_URL = "http://orders.test"
    seen = {}

    def fake_get(url, params, timeout):
        seen.update(url=url, params=params)
        return mock.Mock(**{"raise_for_status.return_value": None, "json.return_value": {"verified": True}})

    monkeypatch.setattr(httpx, "get", fake_get)
    assert review_service.verified_purchase("user-1", "product-1") is True
    assert seen["url"] == "http://orders.test/api/v1/internal/verified-purchase/"
    assert seen["params"] == {"user_id": "user-1", "product_id": "product-1"}


def test_a_failed_orders_call_is_reported_as_unavailable(monkeypatch):
    def broken_get(url, params, timeout):
        raise httpx.ConnectError("orders is down")

    monkeypatch.setattr(httpx, "get", broken_get)
    with pytest.raises(review_service.PurchaseCheckUnavailable):
        review_service.verified_purchase("user-1", "product-1")


def test_search_gets_the_rating_in_the_product_document(customer, lamp, orders):
    write_review(customer, lamp.slug)
    lamp.refresh_from_db()
    document = events.product_document(lamp, revision=1)
    assert document["rating_count"] == 1
    assert document["rating_average"] == "4.00"

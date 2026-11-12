from datetime import timedelta

import pytest
from django.utils import timezone

from ordering.models import Order

pytestmark = pytest.mark.django_db


def transition(admin, number, status):
    return admin.post(f"/api/v1/admin/orders/{number}/transition/", {"status": status}, format="json")


class TestSellerSummary:
    def test_counts_only_paid_sales_of_this_seller(self, customer, other_customer, seller, admin, place_order, pay):
        paid = place_order(customer, items=[("10.00", 2), ("5.00", 1)], seller_id=seller.user_id).data["number"]
        pay(paid)
        place_order(other_customer, items=[("99.00", 1)], seller_id=seller.user_id)  # unpaid: not a sale yet
        place_order(customer, items=[("50.00", 1)])                                 # someone else's product

        data = seller.get("/api/v1/seller/summary/").data

        assert data["revenue"] == "25.00"
        assert data["units_sold"] == 3
        assert data["orders"] == 1
        assert data["products_sold"] == 2
        assert data["to_ship"] == 1

    def test_shipped_orders_still_count_as_sales_but_not_to_ship(self, customer, seller, admin, place_order, pay):
        number = place_order(customer, items=[("10.00", 1)], seller_id=seller.user_id).data["number"]
        pay(number)
        transition(admin, number, "shipped")

        data = seller.get("/api/v1/seller/summary/").data

        assert data["revenue"] == "10.00"
        assert data["to_ship"] == 0

    def test_cancelled_orders_are_not_sales(self, customer, seller, admin, place_order, pay):
        number = place_order(customer, items=[("10.00", 1)], seller_id=seller.user_id).data["number"]
        pay(number)
        transition(admin, number, "cancelled")

        assert seller.get("/api/v1/seller/summary/").data["revenue"] == "0.00"

    def test_daily_units_cover_the_last_seven_days(self, customer, seller, admin, place_order, pay):
        today = place_order(customer, items=[("10.00", 2)], seller_id=seller.user_id).data["number"]
        old = place_order(customer, items=[("10.00", 5)], seller_id=seller.user_id).data["number"]
        for number in (today, old):
            pay(number)
        Order.objects.filter(number=old).update(created_at=timezone.now() - timedelta(days=10))

        days = seller.get("/api/v1/seller/summary/").data["daily_units"]

        assert len(days) == 7
        assert days[-1] == {"date": timezone.now().date().isoformat(), "units": 2}
        assert sum(d["units"] for d in days) == 2

    def test_new_seller_gets_zeros(self, seller):
        data = seller.get("/api/v1/seller/summary/").data

        assert data["revenue"] == "0.00"
        assert data["units_sold"] == 0
        assert [d["units"] for d in data["daily_units"]] == [0] * 7

    @pytest.mark.parametrize("who", ["customer", "admin"])
    def test_only_sellers(self, request, who):
        assert request.getfixturevalue(who).get("/api/v1/seller/summary/").status_code == 403


class TestAdminSummary:
    def test_counts_every_status(self, customer, admin, place_order, pay):
        first = place_order(customer).data["number"]
        place_order(customer)
        pay(first)

        data = admin.get("/api/v1/admin/orders/summary/").data

        assert data["total"] == 2
        assert data["by_status"]["paid"] == 1
        assert data["by_status"]["reserving"] == 1
        assert data["by_status"]["delivered"] == 0

    def test_only_admins(self, customer, seller):
        assert customer.get("/api/v1/admin/orders/summary/").status_code == 403
        assert seller.get("/api/v1/admin/orders/summary/").status_code == 403

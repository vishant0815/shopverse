import pytest

from ordering.models import Order

pytestmark = pytest.mark.django_db


def order_url(number, suffix=""):
    return f"/api/v1/orders/{number}/{suffix}"


def admin_transition(admin, number, status, note=""):
    return admin.post(f"/api/v1/admin/orders/{number}/transition/", {"status": status, "note": note}, format="json")


class TestCustomerOrders:
    def test_list_and_detail_own_orders(self, customer, place_order):
        number = place_order(customer, items=[("10.00", 2), ("5.00", 1)]).data["number"]

        listing = customer.get("/api/v1/orders/")
        assert listing.data["count"] == 1
        assert listing.data["results"][0]["item_count"] == 3

        detail = customer.get(order_url(number))
        assert detail.status_code == 200
        assert len(detail.data["items"]) == 2

    def test_cannot_see_other_customers_orders(self, customer, other_customer, place_order):
        number = place_order(customer).data["number"]

        assert other_customer.get("/api/v1/orders/").data["count"] == 0
        assert other_customer.get(order_url(number)).status_code == 404
        assert other_customer.post(order_url(number, "cancel/")).status_code == 404

    def test_cancel_pending_order(self, customer, place_order):
        number = place_order(customer).data["number"]

        response = customer.post(order_url(number, "cancel/"), {"reason": "Changed my mind"}, format="json")

        assert response.status_code == 200
        assert response.data["status"] == "cancelled"
        assert response.data["history"][-1]["note"] == "Changed my mind"
        assert response.data["can_cancel"] is False

    def test_cannot_cancel_shipped_order(self, customer, admin, place_order):
        number = place_order(customer).data["number"]
        admin_transition(admin, number, "paid")
        admin_transition(admin, number, "shipped")

        assert customer.post(order_url(number, "cancel/")).status_code == 409
        assert Order.objects.get(number=number).status == "shipped"


class TestLifecycle:
    def test_full_happy_path_is_recorded_in_history(self, customer, admin, place_order):
        number = place_order(customer).data["number"]

        for status in ["paid", "shipped", "delivered"]:
            assert admin_transition(admin, number, status).status_code == 200

        history = customer.get(order_url(number)).data["history"]
        assert [h["to_status"] for h in history] == ["pending_payment", "paid", "shipped", "delivered"]

    @pytest.mark.parametrize("path, bad_next", [
        ([], "shipped"),                       # can't ship before payment
        ([], "delivered"),
        (["paid", "shipped"], "cancelled"),    # can't cancel once shipped
        (["paid", "shipped", "delivered"], "paid"),
        (["cancelled"], "paid"),               # cancelled is final
    ])
    def test_illegal_transitions_are_rejected(self, customer, admin, place_order, path, bad_next):
        number = place_order(customer).data["number"]
        for status in path:
            admin_transition(admin, number, status)

        response = admin_transition(admin, number, bad_next)

        assert response.status_code == 409
        assert "allowed" in response.data

    def test_only_admin_can_transition(self, customer, seller, place_order):
        number = place_order(customer).data["number"]

        assert admin_transition(customer, number, "paid").status_code == 403
        assert admin_transition(seller, number, "paid").status_code == 403

    def test_admin_lists_all_orders_with_status_filter(self, customer, other_customer, admin, place_order):
        first = place_order(customer).data["number"]
        place_order(other_customer)
        admin_transition(admin, first, "paid")

        assert admin.get("/api/v1/admin/orders/").data["count"] == 2
        paid = admin.get("/api/v1/admin/orders/", {"status": "paid"}).data
        assert [o["number"] for o in paid["results"]] == [first]

    def test_customers_cannot_use_admin_endpoints(self, customer):
        assert customer.get("/api/v1/admin/orders/").status_code == 403


class TestSellerSales:
    def test_seller_sees_only_their_own_lines(self, customer, seller, place_order, catalogue, address):
        mine = catalogue.add(price="30.00", seller_id=seller.user_id, name="My Product")
        theirs = catalogue.add(price="99.00", name="Someone Else's")
        for variant_id in (mine, theirs):
            customer.post("/api/v1/cart/items/", {"variant_id": variant_id}, format="json")
        customer.post("/api/v1/checkout/", {"shipping_address": address}, format="json")

        response = seller.get("/api/v1/seller/sales/")

        assert response.status_code == 200
        assert [r["product_name"] for r in response.data["results"]] == ["My Product"]
        assert "shipping_address" not in response.data["results"][0]

    def test_customers_cannot_view_sales(self, customer):
        assert customer.get("/api/v1/seller/sales/").status_code == 403

"""The internal endpoint the payments service calls when a payment succeeds."""

import pytest

from ordering.models import Order

from .conftest import make_client

pytestmark = pytest.mark.django_db


@pytest.fixture
def service(db):
    return make_client("service")


@pytest.fixture
def order(customer, place_order):
    return Order.objects.get(number=place_order(customer, items=[("20.00", 1)]).data["number"])


def confirm(client, order, amount=None, currency="GBP", payment_id="pi_123"):
    return client.post(
        f"/api/v1/internal/orders/{order.number}/payment-confirmed/",
        {"payment_id": payment_id, "amount": str(amount if amount is not None else order.total), "currency": currency},
        format="json",
    )


def test_marks_order_paid_and_records_payment(service, order):
    response = confirm(service, order)

    assert response.status_code == 200
    order.refresh_from_db()
    assert order.status == "paid"
    assert order.history.last().note == "Payment pi_123 confirmed"


def test_is_idempotent(service, order):
    confirm(service, order)
    second = confirm(service, order)

    assert second.status_code == 200
    assert order.history.filter(to_status="paid").count() == 1


def test_already_shipped_order_is_left_alone(service, admin, order):
    confirm(service, order)
    admin.post(f"/api/v1/admin/orders/{order.number}/transition/", {"status": "shipped"}, format="json")

    assert confirm(service, order).status_code == 200
    order.refresh_from_db()
    assert order.status == "shipped"


@pytest.mark.parametrize("amount, currency", [("1.00", "GBP"), (None, "USD")])
def test_wrong_amount_or_currency_never_marks_paid(service, order, amount, currency):
    response = confirm(service, order, amount=amount, currency=currency)

    assert response.status_code == 409
    assert response.data["code"] == "amount_mismatch"
    order.refresh_from_db()
    assert order.status == "pending_payment"


def test_cancelled_order_is_reported(service, customer, order):
    customer.post(f"/api/v1/orders/{order.number}/cancel/")

    response = confirm(service, order)

    assert response.status_code == 409
    assert response.data["code"] == "order_cancelled"


@pytest.mark.parametrize("role", ["customer", "seller", "admin"])
def test_only_services_can_call_it(order, role):
    assert confirm(make_client(role), order).status_code == 403


def test_unknown_order_returns_404(service, order):
    order.number = "SV-00000000-NOPE00"
    assert confirm(service, order, amount="20.00").status_code == 404

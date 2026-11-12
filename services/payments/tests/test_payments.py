"""Starting payments and completing them with the fake provider."""

import pytest
from sqlalchemy import func, select

from app import providers as providers_module
from app.db import get_sessionmaker
from app.models import Payment, ProcessedEvent
from app.providers import ProviderError
from app import service
from app.routes import payments as payment_routes

PAYMENTS = "/api/v1/payments"


def start(customer, number):
    return customer.post(PAYMENTS, json={"order_number": number})


def simulate(customer, number, outcome="succeeded"):
    return customer.post(f"{PAYMENTS}/{number}/simulate", json={"outcome": outcome})


def count(model):
    with get_sessionmaker()() as db:
        return db.scalar(select(func.count()).select_from(model))


class TestStart:
    def test_creates_payment_for_the_order_total(self, customer, orders):
        number = orders.add(customer.id, total="59.98")

        response = start(customer, number)

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "requires_payment"
        assert body["provider"] == "fake"
        assert body["amount"] == "59.98"
        assert body["amount_minor"] == 5998
        assert body["currency"] == "GBP"
        assert body["client_secret"].startswith("fake_pi_")

    def test_client_cannot_choose_the_amount(self, customer, orders):
        number = orders.add(customer.id, total="100.00")

        response = customer.post(PAYMENTS, json={"order_number": number, "amount": "0.01"})

        assert response.json()["amount_minor"] == 10000

    def test_starting_again_returns_the_same_payment(self, customer, orders):
        number = orders.add(customer.id)
        first = start(customer, number)
        second = start(customer, number)

        assert second.status_code == 200
        assert second.json()["id"] == first.json()["id"]
        assert count(Payment) == 1

    def test_cannot_pay_for_someone_elses_order(self, customer, other_customer, orders):
        number = orders.add(customer.id)

        assert start(other_customer, number).status_code == 404

    def test_cannot_take_over_an_existing_payment(self, customer, other_customer, orders):
        number = orders.add(customer.id)
        start(customer, number)
        # Even if the orders check were bypassed, the payment row is tied to its owner.
        orders.orders[number]["owner"] = other_customer.id

        assert start(other_customer, number).status_code == 404

    @pytest.mark.parametrize("status", ["paid", "shipped", "cancelled"])
    def test_only_pending_orders_can_be_paid(self, customer, orders, status):
        number = orders.add(customer.id, status=status)

        response = start(customer, number)

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "not_payable"

    def test_orders_service_down_returns_503(self, customer, orders):
        number = orders.add(customer.id)
        orders.down = True

        assert start(customer, number).status_code == 503

    def test_provider_failure_returns_502_and_saves_nothing(self, customer, orders, monkeypatch):
        class BrokenProvider(providers_module.PaymentProvider):
            name = "broken"

            def create_payment(self, **kwargs):
                raise ProviderError("Stripe is down")

            def parse_webhook(self, payload, signature):
                raise ValueError

            def refund(self, **kwargs):
                raise ProviderError("Stripe is down")

        monkeypatch.setattr(payment_routes, "get_provider", lambda: BrokenProvider())
        number = orders.add(customer.id)

        assert start(customer, number).status_code == 502
        assert count(Payment) == 0

    def test_missing_order_number_is_rejected(self, customer, orders):
        assert customer.post(PAYMENTS, json={}).status_code == 422


class TestStatus:
    def test_owner_can_see_status_without_client_secret(self, customer, orders):
        number = orders.add(customer.id)
        start(customer, number)

        response = customer.get(f"{PAYMENTS}/{number}")

        assert response.status_code == 200
        assert response.json()["status"] == "requires_payment"
        assert "client_secret" not in response.json()

    def test_others_cannot_see_it(self, customer, other_customer, orders):
        number = orders.add(customer.id)
        start(customer, number)

        assert other_customer.get(f"{PAYMENTS}/{number}").status_code == 404
        assert simulate(other_customer, number).status_code == 404


class TestCompleting:
    def test_success_is_announced_to_the_orders_saga(self, customer, orders, announced):
        number = orders.add(customer.id, total="59.98")
        payment_id = start(customer, number).json()["id"]

        response = simulate(customer, number)

        assert response.status_code == 200
        assert response.json()["payment"]["status"] == "succeeded"
        assert announced() == [("PaymentSucceeded", {
            "order_number": number, "payment_id": payment_id, "amount": "59.98", "currency": "GBP",
        })]

    def test_paid_order_cannot_be_paid_again(self, customer, orders):
        number = orders.add(customer.id)
        start(customer, number)
        simulate(customer, number)

        response = start(customer, number)

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "already_paid"

    def test_failure_is_recorded_and_can_be_retried(self, customer, orders, announced):
        number = orders.add(customer.id)
        payment_id = start(customer, number).json()["id"]

        failed = simulate(customer, number, "failed")
        assert failed.json()["payment"]["status"] == "failed"
        assert "declined" in failed.json()["payment"]["last_error"]
        assert announced("PaymentFailed") == [("PaymentFailed", {
            "order_number": number, "payment_id": payment_id, "error": "Your card was declined. (simulated)",
        })]

        retry = start(customer, number)
        assert retry.status_code == 200
        assert retry.json()["id"] == payment_id
        assert retry.json()["status"] == "requires_payment"

        assert simulate(customer, number).json()["payment"]["status"] == "succeeded"
        assert [kind for kind, _ in announced()] == ["PaymentFailed", "PaymentSucceeded"]

    def test_success_is_announced_even_if_the_order_was_cancelled_meanwhile(self, customer, orders, announced):
        # The saga is the one that knows the order was cancelled; it asks for the refund itself.
        number = orders.add(customer.id)
        start(customer, number)
        orders.orders[number]["status"] = "cancelled"

        response = simulate(customer, number)

        assert response.json()["payment"]["status"] == "succeeded"
        assert [kind for kind, _ in announced()] == ["PaymentSucceeded"]

    def test_orders_being_down_does_not_block_a_payment(self, customer, orders, announced):
        number = orders.add(customer.id)
        start(customer, number)
        orders.down = True

        response = simulate(customer, number)

        assert response.status_code == 200
        assert response.json()["payment"]["status"] == "succeeded"
        assert len(announced("PaymentSucceeded")) == 1

    def test_a_failed_write_records_nothing(self, customer, orders, monkeypatch):
        number = orders.add(customer.id)
        start(customer, number)

        def broken(*args, **kwargs):
            raise RuntimeError("outbox unavailable")

        real_enqueue = service.enqueue
        monkeypatch.setattr(service, "enqueue", broken)
        with pytest.raises(RuntimeError):
            simulate(customer, number)

        # The payment and its announcement are one transaction: neither happened.
        assert count(ProcessedEvent) == 0
        assert customer.get(f"{PAYMENTS}/{number}").json()["status"] == "requires_payment"

        monkeypatch.setattr(service, "enqueue", real_enqueue)
        assert simulate(customer, number).json()["payment"]["status"] == "succeeded"

    def test_bad_outcome_is_rejected(self, customer, orders):
        number = orders.add(customer.id)
        start(customer, number)

        assert simulate(customer, number, "maybe").status_code == 422

"""Refunds: the orders saga asks for money back, and payments gives it back exactly once.

These run the real consumer (process, with the outbox and processed_messages tables) on
the command envelope, without Kafka.
"""

import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app import service
from app import worker as worker_module
from app.db import get_sessionmaker
from app.messaging import process
from app.models import Payment, PaymentStatus
from app.providers import PaymentEvent, ProviderError
from app.providers.fake_provider import FakeProvider

PAYMENTS = "/api/v1/payments"


class RecordingProvider(FakeProvider):
    """The fake provider, recording refunds and able to refuse them."""

    def __init__(self):
        self.refunds = []
        self.refusing = False

    def refund(self, *, provider_payment_id, amount_minor, idempotency_key):
        if self.refusing:
            raise ProviderError("card network unavailable")
        self.refunds.append((provider_payment_id, amount_minor, idempotency_key))
        return f"re_{idempotency_key}"


@pytest.fixture
def provider(monkeypatch):
    fake = RecordingProvider()
    monkeypatch.setattr(worker_module, "get_provider", lambda: fake)
    return fake


def command(order_number, reason="order_cancelled", message_id=None):
    envelope = {
        "id": str(message_id or uuid.uuid4()), "type": "RefundPayment", "source": "orders",
        "occurred_at": datetime.now(timezone.utc).isoformat(), "key": order_number,
        "data": {"order_number": order_number, "reason": reason},
    }
    return json.dumps(envelope).encode()


def run(raw):
    return process(get_sessionmaker(), worker_module.HANDLERS, "payments.commands", raw)


def paid(customer, orders, total="59.98"):
    number = orders.add(customer.id, total=total)
    customer.post(PAYMENTS, json={"order_number": number})
    customer.post(f"{PAYMENTS}/{number}/simulate", json={"outcome": "succeeded"})
    return number


def payment_for(number):
    with get_sessionmaker()() as db:
        return db.scalar(select(Payment).where(Payment.order_number == number))


class TestRefunding:
    def test_a_paid_order_is_refunded_and_announced(self, customer, orders, provider, announced):
        number = paid(customer, orders)
        payment = payment_for(number)

        assert run(command(number)) == "handled"

        assert payment_for(number).status == PaymentStatus.REFUNDED
        assert provider.refunds == [(payment.provider_payment_id, 5998, f"refund-{payment.id}")]
        assert announced("PaymentRefunded") == [("PaymentRefunded", {
            "order_number": number, "payment_id": str(payment.id), "amount": "59.98",
            "currency": "GBP", "reason": "order_cancelled",
        })]

    def test_a_redelivered_command_refunds_once(self, customer, orders, provider):
        number = paid(customer, orders)
        raw = command(number)

        assert run(raw) == "handled"
        assert run(raw) == "duplicate"

        assert len(provider.refunds) == 1

    def test_a_new_command_for_a_refunded_payment_only_announces_it_again(self, customer, orders, provider, announced):
        number = paid(customer, orders)
        run(command(number))

        run(command(number))  # a re-sent command, with a new message id

        assert len(provider.refunds) == 1
        assert [kind for kind, _ in announced("PaymentRefunded")] == ["PaymentRefunded", "PaymentRefunded"]

    def test_a_provider_refusal_is_reported_and_can_be_retried(self, customer, orders, provider, announced):
        number = paid(customer, orders)
        payment = payment_for(number)
        provider.refusing = True

        run(command(number))

        assert payment_for(number).status == PaymentStatus.REFUND_REQUIRED
        assert announced("RefundFailed") == [("RefundFailed", {
            "order_number": number, "payment_id": str(payment.id),
            "reason": "provider_error", "requested_reason": "order_cancelled",
        })]

        provider.refusing = False
        run(command(number))

        assert payment_for(number).status == PaymentStatus.REFUNDED
        assert len(provider.refunds) == 1

    def test_a_mismatched_payment_is_refunded_for_what_was_taken(self, customer, orders, provider, announced):
        number = orders.add(customer.id, total="59.98")
        customer.post(PAYMENTS, json={"order_number": number})
        with get_sessionmaker()() as db:
            payment = db.scalar(select(Payment).where(Payment.order_number == number))
            service.handle_event(db, PaymentEvent(
                event_id="evt_overpaid", type="succeeded", provider_payment_id=payment.provider_payment_id,
                amount_minor=10000, currency="GBP",
            ))

        run(command(number))

        assert provider.refunds[0][1] == 10000
        assert [data["amount"] for _, data in announced("PaymentSucceeded")] == ["100.00"]
        assert payment_for(number).status == PaymentStatus.REFUNDED


class TestNothingToRefund:
    def test_an_order_with_no_payment_is_reported(self, provider, announced):
        number = "SV-20261112-NOPAY1"

        run(command(number))

        assert provider.refunds == []
        assert announced("RefundFailed") == [("RefundFailed", {
            "order_number": number, "reason": "no_payment", "requested_reason": "order_cancelled",
        })]

    def test_an_unpaid_payment_is_not_refunded(self, customer, orders, provider, announced):
        number = orders.add(customer.id)
        customer.post(PAYMENTS, json={"order_number": number})

        run(command(number))

        assert provider.refunds == []
        assert [data["reason"] for _, data in announced("RefundFailed")] == ["not_paid"]
        assert payment_for(number).status == PaymentStatus.REQUIRES_PAYMENT

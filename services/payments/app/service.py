"""Payment logic, independent of HTTP and of which provider is used."""

import logging
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import orders_client
from .messaging import enqueue
from .models import Payment, PaymentStatus, ProcessedEvent, to_minor_units
from .providers import PaymentEvent, PaymentProvider, ProviderError

logger = logging.getLogger(__name__)

# Payment events for the orders saga: a topic per service, a key per order (docs/events.md).
EVENTS = "payments.events"
# A payment can only be refunded once it has taken money, and only while we still hold it.
REFUNDABLE = {PaymentStatus.SUCCEEDED, PaymentStatus.AMOUNT_MISMATCH, PaymentStatus.REFUND_REQUIRED}


class PaymentError(Exception):
    def __init__(self, status_code: int, code: str, detail: str):
        super().__init__(detail)
        self.status_code, self.code, self.detail = status_code, code, detail


def start_payment(db: Session, provider: PaymentProvider, *, order_number: str, user_id: uuid.UUID,
                  customer_token: str) -> tuple[Payment, bool]:
    """Create a payment for an order, or return the existing one. Returns (payment, created)."""
    try:
        order = orders_client.get_order(order_number, customer_token)
    except orders_client.OrderNotFound:
        raise PaymentError(404, "order_not_found", "Order not found.")
    except orders_client.OrdersUnavailable:
        raise PaymentError(503, "orders_unavailable", "Orders can't be checked right now. Please try again.")

    existing = db.scalar(select(Payment).where(Payment.order_number == order.number))
    if existing:
        if existing.user_id != user_id:
            raise PaymentError(404, "order_not_found", "Order not found.")
        if existing.status == PaymentStatus.SUCCEEDED:
            raise PaymentError(409, "already_paid", "This order has already been paid.")
        if existing.status == PaymentStatus.FAILED:
            # Same provider payment, new attempt (Stripe lets a failed intent be retried).
            existing.status = PaymentStatus.REQUIRES_PAYMENT
            db.commit()
        if existing.status == PaymentStatus.REQUIRES_PAYMENT:
            return existing, False
        raise PaymentError(409, existing.status.value, "This payment needs attention from support.")

    if order.status != "pending_payment":
        raise PaymentError(409, "not_payable", f"An order that is {order.status.replace('_', ' ')} can't be paid.")

    amount_minor = to_minor_units(order.total)
    try:
        created = provider.create_payment(amount_minor=amount_minor, currency=order.currency, order_number=order.number)
    except Exception as exc:  # ProviderError or network trouble
        logger.warning("Provider failed to create payment for %s: %s", order.number, exc)
        raise PaymentError(502, "provider_error", "The payment provider is unavailable. Please try again.")

    payment = Payment(
        order_number=order.number,
        user_id=user_id,
        provider=provider.name,
        provider_payment_id=created.provider_payment_id,
        client_secret=created.client_secret,
        amount_minor=amount_minor,
        currency=order.currency,
    )
    db.add(payment)
    try:
        db.commit()
    except IntegrityError:
        # Two requests for the same order raced; return the one that won.
        db.rollback()
        return db.scalar(select(Payment).where(Payment.order_number == order.number)), False
    return payment, True


def _money(amount_minor: int) -> Decimal:
    return (Decimal(amount_minor) / 100).quantize(Decimal("0.01"))


def _announce(db: Session, type_: str, payment: Payment, **data) -> None:
    """Queue an event for the orders saga. It is sent only when this transaction commits."""
    enqueue(db, EVENTS, type_, payment.order_number,
            {"order_number": payment.order_number, "payment_id": str(payment.id), **data})


def handle_event(db: Session, event: PaymentEvent) -> str:
    """Apply a provider event. Returns a short outcome for the logs and the HTTP response.

    The payment's new state and the event for the orders saga are written in one
    transaction, so the saga hears about a payment exactly when the record changes. Nothing
    here calls another service: if the database fails, the transaction rolls back and the
    provider's retry runs the event again.
    """
    if event.type == "other":
        return "ignored"

    db.add(ProcessedEvent(event_id=event.event_id, event_type=event.type))
    try:
        db.flush()  # a duplicate event id fails here, before any work
    except IntegrityError:
        db.rollback()
        return "duplicate"

    payment = db.scalar(
        select(Payment).where(Payment.provider_payment_id == event.provider_payment_id).with_for_update()
    )
    if payment is None:
        logger.warning("Event %s for unknown payment %s", event.event_id, event.provider_payment_id)
        db.commit()
        return "unknown_payment"

    if event.type == "failed":
        if payment.status == PaymentStatus.REQUIRES_PAYMENT:
            payment.status = PaymentStatus.FAILED
            payment.last_error = event.error_message
            _announce(db, "PaymentFailed", payment, error=event.error_message)
        db.commit()
        return "failed"

    # Succeeded.
    if payment.status == PaymentStatus.SUCCEEDED:
        db.commit()
        return "already_succeeded"

    payment.received_amount_minor = event.amount_minor
    if event.amount_minor != payment.amount_minor or event.currency.upper() != payment.currency.upper():
        payment.status = PaymentStatus.AMOUNT_MISMATCH
        payment.last_error = f"Provider reported {event.amount_minor} {event.currency}"
        logger.error("Amount mismatch on payment %s", payment.id)
    else:
        payment.status = PaymentStatus.SUCCEEDED
        payment.last_error = ""

    # Announce what was actually taken. The saga compares it with the order total and asks
    # for a refund itself if they differ, so a mismatch never marks an order paid.
    _announce(db, "PaymentSucceeded", payment,
              amount=str(_money(event.amount_minor)), currency=event.currency.upper())
    db.commit()
    return payment.status.value


def refund_order(db: Session, provider: PaymentProvider, *, order_number: str, reason: str) -> None:
    """Give back the money taken for an order, at the orders saga's request. The caller commits.

    Refunds exactly once: a repeated command finds the payment already refunded and only
    announces that again. The provider's idempotency key covers the case where the refund
    went through but this transaction failed before it was recorded.
    """
    payment = db.scalar(select(Payment).where(Payment.order_number == order_number).with_for_update())
    if payment is None:
        enqueue(db, EVENTS, "RefundFailed", order_number,
                {"order_number": order_number, "reason": "no_payment", "requested_reason": reason})
        return

    if payment.status == PaymentStatus.REFUNDED:
        _announce(db, "PaymentRefunded", payment, amount=str(_money(_taken(payment))),
                  currency=payment.currency, reason=reason)
        return

    if payment.status not in REFUNDABLE:
        _announce(db, "RefundFailed", payment, reason="not_paid", requested_reason=reason)
        return

    amount_minor = _taken(payment)
    try:
        provider.refund(provider_payment_id=payment.provider_payment_id, amount_minor=amount_minor,
                        idempotency_key=f"refund-{payment.id}")
    except ProviderError as exc:
        logger.error("Refund for %s was refused: %s", order_number, exc)
        payment.status = PaymentStatus.REFUND_REQUIRED
        payment.last_error = f"Refund failed: {exc}"[:255]
        _announce(db, "RefundFailed", payment, reason="provider_error", requested_reason=reason)
        return

    payment.status = PaymentStatus.REFUNDED
    payment.last_error = ""
    _announce(db, "PaymentRefunded", payment, amount=str(_money(amount_minor)),
              currency=payment.currency, reason=reason)


def _taken(payment: Payment) -> int:
    """The amount the provider took, which is what we give back."""
    return payment.received_amount_minor or payment.amount_minor

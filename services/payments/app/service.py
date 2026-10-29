"""Payment logic, independent of HTTP and of which provider is used."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import orders_client
from .models import Payment, PaymentStatus, ProcessedEvent, to_minor_units
from .providers import PaymentEvent, PaymentProvider

logger = logging.getLogger(__name__)


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


def handle_event(db: Session, event: PaymentEvent) -> str:
    """Apply a provider event. Returns a short outcome for logging and the HTTP response.

    Everything happens in one transaction: if the orders service can't be reached, the
    transaction rolls back (event not marked processed) and OrdersUnavailable propagates,
    so the webhook answers 503 and the provider retries later.
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
        db.commit()
        return "failed"

    # Succeeded.
    if payment.status == PaymentStatus.SUCCEEDED:
        db.commit()
        return "already_succeeded"
    if event.amount_minor != payment.amount_minor or event.currency.upper() != payment.currency.upper():
        payment.status = PaymentStatus.AMOUNT_MISMATCH
        payment.last_error = f"Provider reported {event.amount_minor} {event.currency}"
        db.commit()
        logger.error("Amount mismatch on payment %s", payment.id)
        return "amount_mismatch"

    try:
        result = orders_client.confirm_payment(payment.order_number, str(payment.id), payment.amount, payment.currency)
    except orders_client.OrdersUnavailable:
        db.rollback()
        raise

    if result.ok:
        payment.status = PaymentStatus.SUCCEEDED
        payment.last_error = ""
    elif result.code == "order_cancelled":
        payment.status = PaymentStatus.REFUND_REQUIRED
        payment.last_error = "Order was cancelled before the payment completed."
    else:
        payment.status = PaymentStatus.AMOUNT_MISMATCH
        payment.last_error = f"Orders service rejected the payment: {result.code}"
    db.commit()
    return payment.status.value

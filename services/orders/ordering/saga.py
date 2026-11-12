"""The checkout saga. Orders is the orchestrator (see docs/events.md).

    place order ──► ReserveStock ──► StockReserved ──► (customer pays) ──► PaymentSucceeded
         │                │                                                     │
         │                └─► StockRejected: cancel, nothing to undo            └─► Paid, CommitStock
         └─ timeouts and cancellations undo what was done: ReleaseStock, RefundPayment

Every function here runs inside a database transaction with the order row locked, and
sends commands by writing them to the outbox in that same transaction. So the order's
new state and the commands that follow from it are saved together or not at all.
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from messaging.kafka import enqueue

from .models import CheckoutSaga, Order

log = logging.getLogger("saga")

INVENTORY = "inventory.commands"
PAYMENTS = "payments.commands"
ORDERS = "orders.events"

State = CheckoutSaga.State
Code = CheckoutSaga.CancelCode


# Starting ------------------------------------------------------------------------------

def start(order: Order) -> CheckoutSaga:
    """Called by place_order, inside its transaction."""
    saga = CheckoutSaga.objects.create(order=order, state=State.RESERVING)
    lines = [{"variant_id": str(item.variant_id), "quantity": item.quantity} for item in order.items.all()]
    enqueue(INVENTORY, "ReserveStock", order.number, {"order_number": order.number, "lines": lines})
    enqueue(ORDERS, "OrderPlaced", order.number, {
        "order_number": order.number, "user_id": str(order.user_id),
        "total": str(order.total), "currency": order.currency,
    })
    return saga


# Helpers -------------------------------------------------------------------------------

def _locked(order_number: str):
    """The order and its saga, locked for the rest of the transaction; (None, None) if unknown."""
    order = Order.objects.select_for_update().filter(number=order_number).first()
    if order is None:
        log.warning("message for unknown order %s", order_number)
        return None, None
    saga = CheckoutSaga.objects.select_for_update().filter(order=order).first()
    return order, saga


def _money(amount: Decimal, currency: str) -> str:
    return f"£{amount:.2f}" if currency == "GBP" else f"{amount:.2f} {currency}"


def _describe(item) -> str:
    options = ", ".join(part for part in (item.colour, item.size) if part)
    return f"{item.product_name} ({options})" if options else item.product_name


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _request_refund(order: Order, saga: CheckoutSaga, amount: Decimal, reason: str) -> None:
    saga.refund_status = CheckoutSaga.RefundStatus.REQUESTED
    saga.refund_amount = amount
    saga.save()
    enqueue(PAYMENTS, "RefundPayment", order.number, {"order_number": order.number, "reason": reason})


def _cancel(order: Order, saga: CheckoutSaga, *, code: str, detail: str, note: str, by=None,
            release: bool = True, final_state: str = State.CANCELLED) -> None:
    """Cancel the order and undo whatever the saga had done so far."""
    was = order.status
    order.move_to(Order.Status.CANCELLED, changed_by=by, note=note[:255])
    saga.state = final_state
    saga.cancel_code = code
    saga.cancel_detail = detail[:500]
    saga.hold_expires_at = None
    saga.save()
    if release:
        # Also sent while still reserving: if the reservation lands after this, inventory
        # handles the reserve first (same order, same partition) and then releases it.
        enqueue(INVENTORY, "ReleaseStock", order.number, {"order_number": order.number, "reason": code})
    if was == Order.Status.PAID:
        _request_refund(order, saga, saga.paid_amount or order.total, reason=code)
    enqueue(ORDERS, "OrderCancelled", order.number, {"order_number": order.number, "reason": code})


# Replies from inventory ----------------------------------------------------------------

def stock_reserved(message: dict) -> None:
    order, saga = _locked(message["data"]["order_number"])
    if saga is None or saga.state != State.RESERVING:
        return  # too late: the order was cancelled meanwhile, and its release is on its way
    window = settings.PAYMENT_WINDOW_MINUTES
    saga.state = State.AWAITING_PAYMENT
    saga.hold_expires_at = timezone.now() + timedelta(minutes=window)
    saga.save()
    order.move_to(Order.Status.PENDING_PAYMENT, changed_by=None, note=f"Items held for {window} minutes")


def stock_rejected(message: dict) -> None:
    data = message["data"]
    order, saga = _locked(data["order_number"])
    if saga is None or saga.state != State.RESERVING:
        return
    missing = {line["variant_id"] for line in data.get("unavailable", [])}
    names = [_describe(item) for item in order.items.all() if str(item.variant_id) in missing]
    if names:
        detail = f"{_join(names)} sold out before we could hold it for you."
        if len(names) > 1:
            detail = f"{_join(names)} sold out before we could hold them for you."
    else:
        detail = "Some items sold out before we could hold them for you."
    # Nothing was held and nothing was charged, so there's nothing to undo.
    _cancel(order, saga, code=Code.SOLD_OUT, detail=detail, note=f"Sold out: {detail}", release=False,
            final_state=State.FAILED)


# Replies from payments -----------------------------------------------------------------

def payment_succeeded(message: dict) -> None:
    data = message["data"]
    order, saga = _locked(data["order_number"])
    if order is None:
        return
    if saga is None:  # an order from before the saga existed
        saga = CheckoutSaga.objects.create(order=order, state=State.AWAITING_PAYMENT)
    amount, currency = Decimal(data["amount"]), data["currency"].upper()
    saga.payment_id = data["payment_id"]

    if order.status in (Order.Status.PAID, Order.Status.SHIPPED, Order.Status.DELIVERED):
        saga.save()
        return  # already confirmed

    if order.status == Order.Status.PENDING_PAYMENT:
        if amount != order.total or currency != order.currency:
            # Never mark an order paid for the wrong amount. Give the money back; the
            # items stay held and the customer can pay again.
            order.add_note(f"Payment of {_money(amount, currency)} didn't match the total and is being refunded")
            _request_refund(order, saga, amount, reason="amount_mismatch")
            return
        saga.state = State.COMPLETED
        saga.paid_amount = amount
        saga.hold_expires_at = None
        saga.save()
        order.move_to(Order.Status.PAID, changed_by=None, note=f"Payment {data['payment_id']} confirmed")
        enqueue(INVENTORY, "CommitStock", order.number, {"order_number": order.number})
        enqueue(ORDERS, "OrderConfirmed", order.number, {
            "order_number": order.number, "user_id": str(order.user_id),
            "total": str(order.total), "currency": order.currency,
        })
        return

    # Cancelled (or somehow not yet holding stock): the money must go back.
    saga.paid_amount = amount
    order.add_note(f"Payment of {_money(amount, currency)} arrived after the order was cancelled and is being refunded")
    _request_refund(order, saga, amount, reason="order_cancelled")


def payment_refunded(message: dict) -> None:
    data = message["data"]
    order, saga = _locked(data["order_number"])
    if saga is None or saga.refund_status == CheckoutSaga.RefundStatus.REFUNDED:
        return
    amount = Decimal(data.get("amount") or saga.refund_amount or 0)
    saga.refund_status = CheckoutSaga.RefundStatus.REFUNDED
    saga.refund_amount = amount
    saga.save()
    order.add_note(f"Payment of {_money(amount, order.currency)} refunded")


def refund_failed(message: dict) -> None:
    order, saga = _locked(message["data"]["order_number"])
    if saga is None:
        return
    saga.refund_status = CheckoutSaga.RefundStatus.FAILED
    saga.save()
    order.add_note("Refund failed and needs attention from support")


HANDLERS = {
    "StockReserved": stock_reserved,
    "StockRejected": stock_rejected,
    "PaymentSucceeded": payment_succeeded,
    "PaymentRefunded": payment_refunded,
    "RefundFailed": refund_failed,
}


# Cancelling (from the API) -------------------------------------------------------------

def cancel(order: Order, *, by, by_admin: bool, note: str = "") -> None:
    """Cancel an order the caller has already locked, and undo the saga's steps."""
    saga = CheckoutSaga.objects.select_for_update().filter(order=order).first()
    if by_admin:
        code, detail, default_note = Code.ADMIN, "This order was cancelled by Shopverse.", "Cancelled by admin"
    else:
        code, detail, default_note = Code.CUSTOMER, "You cancelled this order.", "Cancelled by customer"
    if saga is None:  # an order from before the saga existed: just cancel it
        order.move_to(Order.Status.CANCELLED, changed_by=by, note=note or default_note)
        return
    _cancel(order, saga, code=code, detail=detail, note=note or default_note, by=by)


# Timeouts (run by the worker every few seconds) ---------------------------------------

def expire_checkouts(now=None) -> int:
    """Cancel checkouts that weren't paid in time, or never heard back from inventory."""
    now = now or timezone.now()
    window = settings.PAYMENT_WINDOW_MINUTES
    expired = list(CheckoutSaga.objects.filter(state=State.AWAITING_PAYMENT, hold_expires_at__lt=now)
                   .values_list("order__number", flat=True)[:100])
    stuck = list(CheckoutSaga.objects.filter(
        state=State.RESERVING, started_at__lt=now - timedelta(seconds=settings.STOCK_CHECK_TIMEOUT_SECONDS),
    ).values_list("order__number", flat=True)[:100])

    count = 0
    for number in expired:
        with transaction.atomic():
            order, saga = _locked(number)
            # Look again under the lock: the payment may have just arrived.
            if saga and saga.state == State.AWAITING_PAYMENT and saga.hold_expires_at < now:
                _cancel(order, saga, code=Code.NOT_PAID_IN_TIME,
                        detail=f"It wasn't paid within {window} minutes, so the items went back on sale.",
                        note="Not paid in time; items released")
                count += 1
    for number in stuck:
        with transaction.atomic():
            order, saga = _locked(number)
            if saga and saga.state == State.RESERVING:
                _cancel(order, saga, code=Code.STOCK_CHECK_TIMEOUT,
                        detail="We couldn't check stock in time.",
                        note="Stock check timed out")
                count += 1
    if count:
        log.info("cancelled %s timed-out checkouts", count)
    return count

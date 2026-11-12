"""The checkout saga: what orders does with each reply, and what it undoes when."""

import uuid
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from ordering.models import CheckoutSaga, Order
from ordering.saga import expire_checkouts

pytestmark = pytest.mark.django_db


def order_of(number):
    return Order.objects.select_related("saga").get(number=number)


def sent(outbox, *types):
    return [(topic, kind) for topic, kind, _ in outbox() if not types or kind in types]


def cancel(client, number, reason=""):
    return client.post(f"/api/v1/orders/{number}/cancel/", {"reason": reason}, format="json")


def admin_cancel(admin, number):
    return admin.post(f"/api/v1/admin/orders/{number}/transition/", {"status": "cancelled"}, format="json")


# Starting ------------------------------------------------------------------------------

def test_placing_an_order_asks_inventory_to_hold_the_items(customer, place_order, outbox):
    response = place_order(customer, items=[("10.00", 2), ("5.00", 1)])
    number = response.data["number"]

    assert response.data["status"] == "reserving"
    assert order_of(number).saga.state == "reserving"
    (_, _, reserve), (_, _, placed) = [m for m in outbox()]
    assert sent(outbox) == [("inventory.commands", "ReserveStock"), ("orders.events", "OrderPlaced")]
    assert reserve["order_number"] == number
    assert sorted(line["quantity"] for line in reserve["lines"]) == [1, 2]
    assert placed["total"] == response.data["total"]


def test_a_failed_checkout_sends_nothing(customer, outbox):
    response = customer.post("/api/v1/checkout/", {"shipping_address": {}}, format="json")

    assert response.status_code == 400
    assert outbox() == []


# Inventory replies ---------------------------------------------------------------------

def test_held_items_open_payment_for_a_limited_time(customer, place_order, hold):
    number = place_order(customer).data["number"]

    hold(number)

    order = order_of(number)
    assert order.status == "pending_payment"
    assert order.saga.state == "awaiting_payment"
    remaining = order.saga.hold_expires_at - timezone.now()
    assert timedelta(minutes=14) < remaining <= timedelta(minutes=15)
    detail = customer.get(f"/api/v1/orders/{number}/").data
    assert detail["hold_expires_at"] is not None
    assert detail["history"][-1]["note"] == "Items held for 15 minutes"


def test_a_sold_out_item_cancels_the_order_and_says_which(customer, place_order, catalogue, address, deliver,
                                                          outbox):
    lamp = catalogue.add(price="45.00", name="Arc Desk Lamp", colour="Graphite", size="")
    customer.post("/api/v1/cart/items/", {"variant_id": lamp, "quantity": 2}, format="json")
    number = customer.post("/api/v1/checkout/", {"shipping_address": address}, format="json").data["number"]

    deliver("StockRejected", {"order_number": number,
                              "unavailable": [{"variant_id": lamp, "requested": 2, "available": 1}]})

    order = order_of(number)
    assert order.status == "cancelled"
    assert order.saga.state == "failed"
    detail = customer.get(f"/api/v1/orders/{number}/").data
    assert detail["cancellation"] == {
        "code": "sold_out", "detail": "Arc Desk Lamp (Graphite) sold out before we could hold it for you."}
    assert detail["refund"] is None
    # Nothing was held or charged, so nothing is undone.
    assert sent(outbox, "ReleaseStock", "RefundPayment") == []
    assert sent(outbox)[-1] == ("orders.events", "OrderCancelled")


def test_a_late_hold_for_a_cancelled_order_changes_nothing(customer, place_order, hold, outbox):
    number = place_order(customer).data["number"]
    cancel(customer, number)

    hold(number)

    assert order_of(number).status == "cancelled"
    # The release sent with the cancellation undoes the hold that just landed.
    assert sent(outbox, "ReleaseStock") == [("inventory.commands", "ReleaseStock")]


def test_the_same_reply_twice_is_handled_once(customer, place_order, deliver):
    number = place_order(customer).data["number"]
    message_id = uuid.uuid4()

    assert deliver("StockReserved", {"order_number": number}, message_id=message_id) == "handled"
    assert deliver("StockReserved", {"order_number": number}, message_id=message_id) == "duplicate"

    assert [h.to_status for h in order_of(number).history.all()] == ["reserving", "pending_payment"]


def test_replies_about_unknown_orders_are_ignored_safely(deliver):
    assert deliver("StockReserved", {"order_number": "SV-NOPE"}) == "handled"
    assert deliver("PaymentSucceeded", {"order_number": "SV-NOPE", "payment_id": "p", "amount": "1.00",
                                        "currency": "GBP"}) == "handled"


# Payment replies -----------------------------------------------------------------------

def test_a_payment_confirms_the_order_and_the_sale(customer, place_order, pay, outbox):
    number = place_order(customer).data["number"]

    pay(number, payment_id="pay_123")

    order = order_of(number)
    assert order.status == "paid"
    assert order.saga.state == "completed"
    assert order.saga.payment_id == "pay_123"
    assert order.saga.hold_expires_at is None
    assert sent(outbox)[-2:] == [("inventory.commands", "CommitStock"), ("orders.events", "OrderConfirmed")]


def test_a_repeated_payment_report_confirms_only_once(customer, place_order, pay, deliver, outbox):
    number = place_order(customer).data["number"]
    pay(number)

    deliver("PaymentSucceeded", {"order_number": number, "payment_id": "pay_test",
                                 "amount": str(order_of(number).total), "currency": "GBP"})

    assert len(sent(outbox, "CommitStock")) == 1
    assert sent(outbox, "RefundPayment") == []


def test_a_payment_for_the_wrong_amount_is_refunded_not_accepted(customer, place_order, hold, deliver, outbox):
    number = place_order(customer, items=[("10.00", 1)]).data["number"]
    hold(number)

    deliver("PaymentSucceeded", {"order_number": number, "payment_id": "pay_1", "amount": "1.00",
                                 "currency": "GBP"})

    order = order_of(number)
    assert order.status == "pending_payment"  # still payable
    assert order.saga.refund_status == "requested"
    assert sent(outbox, "RefundPayment", "CommitStock") == [("payments.commands", "RefundPayment")]
    assert "didn't match" in order.history.last().note


def test_a_payment_after_cancellation_is_refunded(customer, place_order, hold, deliver, outbox):
    number = place_order(customer).data["number"]
    hold(number)
    cancel(customer, number)

    deliver("PaymentSucceeded", {"order_number": number, "payment_id": "pay_1",
                                 "amount": str(order_of(number).total), "currency": "GBP"})

    order = order_of(number)
    assert order.status == "cancelled"
    assert order.saga.refund_status == "requested"
    assert sent(outbox, "RefundPayment", "CommitStock") == [("payments.commands", "RefundPayment")]
    assert customer.get(f"/api/v1/orders/{number}/").data["refund"] == {
        "status": "requested", "amount": str(order.total)}


def test_a_confirmed_refund_is_recorded(customer, place_order, pay, deliver):
    number = place_order(customer).data["number"]
    pay(number)
    cancel(customer, number)

    deliver("PaymentRefunded", {"order_number": number, "payment_id": "pay_test", "amount": str(order_of(number).total)})

    order = order_of(number)
    assert order.saga.refund_status == "refunded"
    assert order.history.last().note == f"Payment of £{order.total} refunded"
    assert customer.get(f"/api/v1/orders/{number}/").data["refund"]["status"] == "refunded"


def test_a_failed_refund_is_flagged(customer, place_order, pay, deliver):
    number = place_order(customer).data["number"]
    pay(number)
    cancel(customer, number)

    deliver("RefundFailed", {"order_number": number, "payment_id": "pay_test", "reason": "card closed"})

    assert order_of(number).saga.refund_status == "failed"


# Cancelling ----------------------------------------------------------------------------

def test_cancelling_while_checking_stock_releases_whatever_gets_held(customer, place_order, outbox):
    number = place_order(customer).data["number"]

    assert cancel(customer, number).status_code == 200

    assert sent(outbox)[-2:] == [("inventory.commands", "ReleaseStock"), ("orders.events", "OrderCancelled")]
    assert customer.get(f"/api/v1/orders/{number}/").data["cancellation"]["code"] == "customer"


def test_cancelling_before_payment_releases_the_items(customer, place_order, hold, outbox):
    number = place_order(customer).data["number"]
    hold(number)

    cancel(customer, number, reason="Changed my mind")

    order = order_of(number)
    assert order.saga.state == "cancelled"
    assert order.history.last().note == "Changed my mind"
    assert sent(outbox, "ReleaseStock", "RefundPayment") == [("inventory.commands", "ReleaseStock")]


def test_cancelling_after_payment_restocks_and_refunds(customer, place_order, pay, outbox):
    number = place_order(customer, items=[("20.00", 1)]).data["number"]
    pay(number)

    cancel(customer, number)

    order = order_of(number)
    assert order.status == "cancelled"
    assert order.saga.refund_status == "requested"
    assert order.saga.refund_amount == order.total
    assert sent(outbox, "ReleaseStock", "RefundPayment") == [
        ("inventory.commands", "ReleaseStock"), ("payments.commands", "RefundPayment")]


def test_an_admin_cancelling_a_paid_order_also_refunds(customer, admin, place_order, pay, outbox):
    number = place_order(customer).data["number"]
    pay(number)

    assert admin_cancel(admin, number).status_code == 200

    assert sent(outbox, "RefundPayment") == [("payments.commands", "RefundPayment")]
    assert order_of(number).saga.cancel_code == "admin"


def test_orders_from_before_the_saga_can_still_be_cancelled(customer, place_order, outbox):
    number = place_order(customer).data["number"]
    CheckoutSaga.objects.filter(order__number=number).delete()
    before = len(outbox())

    assert cancel(customer, number).status_code == 200

    assert order_of(number).status == "cancelled"
    assert len(outbox()) == before


# Timeouts ------------------------------------------------------------------------------

def test_an_unpaid_order_is_cancelled_when_its_hold_runs_out(customer, place_order, hold, outbox):
    number = place_order(customer).data["number"]
    hold(number)
    later = timezone.now() + timedelta(minutes=16)

    assert expire_checkouts(now=later) == 1

    order = order_of(number)
    assert order.status == "cancelled"
    assert order.saga.cancel_code == "not_paid_in_time"
    assert "15 minutes" in order.saga.cancel_detail
    assert sent(outbox, "ReleaseStock") == [("inventory.commands", "ReleaseStock")]


def test_holds_that_have_not_run_out_are_left_alone(customer, place_order, hold, pay):
    waiting = place_order(customer).data["number"]
    hold(waiting)
    paid = place_order(customer).data["number"]
    pay(paid)

    assert expire_checkouts(now=timezone.now() + timedelta(minutes=10)) == 0
    assert expire_checkouts(now=timezone.now() + timedelta(hours=1)) == 1  # only the unpaid one

    assert order_of(paid).status == "paid"


def test_a_payment_after_the_hold_ran_out_is_refunded(customer, place_order, hold, deliver, outbox):
    number = place_order(customer).data["number"]
    hold(number)
    expire_checkouts(now=timezone.now() + timedelta(minutes=16))

    deliver("PaymentSucceeded", {"order_number": number, "payment_id": "pay_late",
                                 "amount": str(order_of(number).total), "currency": "GBP"})

    assert order_of(number).status == "cancelled"
    assert sent(outbox, "RefundPayment") == [("payments.commands", "RefundPayment")]


@override_settings(STOCK_CHECK_TIMEOUT_SECONDS=60)
def test_a_stock_check_that_never_answers_is_given_up(customer, place_order, outbox):
    number = place_order(customer).data["number"]

    assert expire_checkouts(now=timezone.now() + timedelta(seconds=30)) == 0
    assert expire_checkouts(now=timezone.now() + timedelta(seconds=90)) == 1

    order = order_of(number)
    assert order.saga.cancel_code == "stock_check_timeout"
    # Released in case the reservation lands after all.
    assert sent(outbox, "ReleaseStock") == [("inventory.commands", "ReleaseStock")]


@override_settings(PAYMENT_WINDOW_MINUTES=5)
def test_the_payment_window_is_configurable(customer, place_order, hold):
    number = place_order(customer).data["number"]
    hold(number)

    remaining = order_of(number).saga.hold_expires_at - timezone.now()
    assert timedelta(minutes=4) < remaining <= timedelta(minutes=5)

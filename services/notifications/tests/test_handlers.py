"""What each event does, run through the same processing the worker uses."""

import smtplib
import uuid

import pytest
from sqlalchemy import select

from app.db import get_sessionmaker
from app.messaging import TOPICS
from app.models import NotificationLog, OrderCustomer, ProcessedMessage, Recipient
from app.handlers import RecipientUnknown

from .conftest import CUSTOMER, CUSTOMER_EMAIL

ORDER = "SV-20261116-AAAAAA"
ITEMS = [{"name": "Trail running shoes", "colour": "Black", "size": "UK 9", "quantity": 1,
          "unit_price": "64.00", "line_total": "64.00"}]


def placed(deliver, number=ORDER):
    return deliver("orders.events", "OrderPlaced", {
        "order_number": number, "user_id": str(CUSTOMER), "total": "64.00", "currency": "GBP", "items": ITEMS,
    }, key=number)


def sent_kinds(db_session):
    return [row.kind for row in db_session.scalars(select(NotificationLog)).all()]


def test_the_topics_the_service_reads_are_the_three_event_topics():
    assert sorted(TOPICS) == ["orders.events", "payments.events", "users.events"]


class TestContactDetails:
    def test_a_registered_customer_is_copied_and_a_change_replaces_it(self, deliver, customer_registered):
        deliver("users.events", "UserContactChanged", {
            "user_id": str(CUSTOMER), "email": "new@example.com", "first_name": "Nia", "last_name": "Smith",
        }, key=str(CUSTOMER))

        with get_sessionmaker()() as db:
            recipient = db.get(Recipient, CUSTOMER)
            assert (recipient.email, recipient.last_name) == ("new@example.com", "Smith")

    def test_a_contact_event_sends_nothing(self, mailer, customer_registered):
        assert mailer.sent == []


class TestOrderEmails:
    def test_placing_an_order_emails_the_customer_and_logs_it(self, mailer, deliver, customer_registered):
        assert placed(deliver) == "handled"

        [(to_address, email)] = mailer.sent
        assert to_address == CUSTOMER_EMAIL
        assert email.subject == f"Complete your order {ORDER} within 15 minutes"
        with get_sessionmaker()() as db:
            assert sent_kinds(db) == ["order_placed"]
            assert db.get(OrderCustomer, ORDER).user_id == CUSTOMER

    def test_a_confirmed_payment_emails_the_confirmation(self, mailer, deliver, customer_registered):
        placed(deliver)
        deliver("orders.events", "OrderConfirmed", {
            "order_number": ORDER, "user_id": str(CUSTOMER), "total": "64.00", "currency": "GBP", "items": ITEMS,
        }, key=ORDER)

        assert [email.subject for _, email in mailer.sent][-1] == f"Payment received for order {ORDER}"

    def test_a_cancellation_is_found_through_the_order_number(self, mailer, deliver, customer_registered):
        placed(deliver)
        deliver("orders.events", "OrderCancelled", {"order_number": ORDER, "reason": "not_paid_in_time"}, key=ORDER)

        assert mailer.sent[-1][0] == CUSTOMER_EMAIL
        assert mailer.sent[-1][1].subject == f"Order {ORDER} was cancelled"

    def test_a_failed_payment_is_found_through_the_order_number(self, mailer, deliver, customer_registered):
        placed(deliver)
        deliver("payments.events", "PaymentFailed", {
            "order_number": ORDER, "payment_id": str(uuid.uuid4()), "error": "card_declined",
        }, key=ORDER)

        assert mailer.sent[-1][1].subject == f"Your payment for {ORDER} didn't go through"

    def test_a_refund_emails_the_amount(self, mailer, deliver, customer_registered):
        placed(deliver)
        deliver("payments.events", "PaymentRefunded", {
            "order_number": ORDER, "payment_id": str(uuid.uuid4()), "amount": "64.00", "currency": "GBP",
            "reason": "customer",
        }, key=ORDER)

        assert mailer.sent[-1][1].subject == f"We've refunded £64.00 for order {ORDER}"


class TestWaitingAndRepeats:
    def test_an_order_for_a_customer_not_yet_known_waits_rather_than_failing(self, mailer, deliver):
        with pytest.raises(RecipientUnknown):
            placed(deliver)

        # Nothing sent, and nothing recorded as handled, so the message is tried again later.
        assert mailer.sent == []
        with get_sessionmaker()() as db:
            assert db.scalars(select(ProcessedMessage)).all() == []
            assert db.get(OrderCustomer, ORDER) is None

    def test_a_cancellation_for_an_unknown_order_waits(self, deliver):
        with pytest.raises(RecipientUnknown):
            deliver("orders.events", "OrderCancelled", {"order_number": "SV-NOPE", "reason": "sold_out"})

    def test_the_same_message_twice_is_sent_once(self, mailer, deliver, customer_registered):
        message_id = uuid.uuid4()
        assert placed(deliver, number=ORDER) == "handled"
        first = deliver("orders.events", "OrderConfirmed", {
            "order_number": ORDER, "user_id": str(CUSTOMER), "total": "64.00", "currency": "GBP", "items": ITEMS,
        }, key=ORDER, message_id=message_id)
        again = deliver("orders.events", "OrderConfirmed", {
            "order_number": ORDER, "user_id": str(CUSTOMER), "total": "64.00", "currency": "GBP", "items": ITEMS,
        }, key=ORDER, message_id=message_id)

        assert (first, again) == ("handled", "duplicate")
        assert sum(1 for _, e in mailer.sent if e.subject.startswith("Payment received")) == 1

    def test_events_nobody_emails_about_are_ignored(self, deliver, customer_registered):
        outcome = deliver("payments.events", "RefundFailed", {
            "order_number": ORDER, "payment_id": str(uuid.uuid4()), "reason": "provider_error",
        })
        assert outcome == "ignored"


class TestOneTransaction:
    def test_a_failed_send_records_nothing_so_the_message_can_be_retried(self, mailer, deliver, customer_registered):
        mailer.fail_with = smtplib.SMTPServerDisconnected("relay went away")

        with pytest.raises(smtplib.SMTPServerDisconnected):
            placed(deliver)

        with get_sessionmaker()() as db:
            assert db.scalars(select(NotificationLog)).all() == []
            # Only the failed message is rolled back; the fixture's registration was handled earlier.
            assert db.scalars(select(ProcessedMessage).where(ProcessedMessage.type == "OrderPlaced")).all() == []
            assert db.get(OrderCustomer, ORDER) is None

        mailer.fail_with = None
        assert placed(deliver) == "handled"
        assert len(mailer.sent) == 1

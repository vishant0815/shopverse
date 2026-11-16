"""What each event does.

Contact events keep a copy of the customer's details. Order and payment events send an
email to the customer they belong to, and record that it was sent.

A send happens inside the message's database transaction. If the service crashes after the
email leaves but before the commit, the message is read again and the customer may get the
same email twice. A duplicate is preferred to a lost order confirmation, so it is accepted.
"""

import uuid

from sqlalchemy.orm import Session

from . import emails
from .config import Settings
from .messaging import Handler, Retryable
from .models import NotificationLog, OrderCustomer, Recipient


class RecipientUnknown(Retryable):
    """No contact details (or no owning customer) yet. users.events and orders.events are
    separate topics, so this can clear up on its own within the wait limit."""


def upsert_recipient(db: Session, envelope: dict) -> None:
    data = envelope["data"]
    user_id = uuid.UUID(data["user_id"])
    recipient = db.get(Recipient, user_id)
    if recipient is None:
        recipient = Recipient(user_id=user_id)
        db.add(recipient)
    # One customer's messages are read in order (keyed by user id), so the latest one wins.
    recipient.email = data["email"]
    recipient.first_name = data.get("first_name", "")
    recipient.last_name = data.get("last_name", "")


def remember_order_customer(db: Session, user_id: uuid.UUID, order_number: str) -> None:
    if db.get(OrderCustomer, order_number) is None:
        db.add(OrderCustomer(order_number=order_number, user_id=user_id))


def customer_of(db: Session, order_number: str) -> uuid.UUID:
    link = db.get(OrderCustomer, order_number)
    if link is None:
        raise RecipientUnknown(f"no customer recorded for order {order_number} yet")
    return link.user_id


def build_handlers(settings: Settings, mailer) -> dict[str, Handler]:
    def send(db: Session, envelope: dict, kind: str, user_id: uuid.UUID, order_number: str, build) -> None:
        recipient = db.get(Recipient, user_id)
        if recipient is None:
            raise RecipientUnknown(f"no contact details for customer {user_id} yet")
        mailer.send(recipient.email, build(recipient.first_name))
        db.add(NotificationLog(
            message_id=uuid.UUID(envelope["id"]), kind=kind, order_number=order_number, user_id=user_id,
        ))

    def on_contact(db: Session, envelope: dict) -> None:
        upsert_recipient(db, envelope)

    def on_order_placed(db: Session, envelope: dict) -> None:
        data = envelope["data"]
        number = data["order_number"]
        user_id = uuid.UUID(data["user_id"])
        remember_order_customer(db, user_id, number)
        send(db, envelope, "order_placed", user_id, number, lambda name: emails.order_placed(
            first_name=name, order_number=number, items=data.get("items", []), total=data["total"],
            currency=data["currency"], window_minutes=settings.payment_window_minutes,
            site_url=settings.site_url,
        ))

    def on_order_confirmed(db: Session, envelope: dict) -> None:
        data = envelope["data"]
        number = data["order_number"]
        user_id = uuid.UUID(data["user_id"])
        remember_order_customer(db, user_id, number)
        send(db, envelope, "order_confirmed", user_id, number, lambda name: emails.order_confirmed(
            first_name=name, order_number=number, items=data.get("items", []), total=data["total"],
            currency=data["currency"], site_url=settings.site_url,
        ))

    def on_order_cancelled(db: Session, envelope: dict) -> None:
        data = envelope["data"]
        number = data["order_number"]
        user_id = customer_of(db, number)
        send(db, envelope, "order_cancelled", user_id, number, lambda name: emails.order_cancelled(
            first_name=name, order_number=number, reason=data.get("reason", ""), site_url=settings.site_url,
        ))

    def on_payment_failed(db: Session, envelope: dict) -> None:
        number = envelope["data"]["order_number"]
        user_id = customer_of(db, number)
        send(db, envelope, "payment_failed", user_id, number, lambda name: emails.payment_failed(
            first_name=name, order_number=number, site_url=settings.site_url,
        ))

    def on_refund_issued(db: Session, envelope: dict) -> None:
        data = envelope["data"]
        number = data["order_number"]
        user_id = customer_of(db, number)
        send(db, envelope, "refund_issued", user_id, number, lambda name: emails.refund_issued(
            first_name=name, order_number=number, amount=data["amount"], currency=data["currency"],
            reason=data.get("reason", ""), site_url=settings.site_url,
        ))

    return {
        "UserRegistered": on_contact,
        "UserContactChanged": on_contact,
        "OrderPlaced": on_order_placed,
        "OrderConfirmed": on_order_confirmed,
        "OrderCancelled": on_order_cancelled,
        "PaymentFailed": on_payment_failed,
        "PaymentRefunded": on_refund_issued,
    }

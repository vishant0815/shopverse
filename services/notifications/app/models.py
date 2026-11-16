import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Recipient(Base):
    """A customer's contact details, copied from users.events so an email needs no call to users."""

    __tablename__ = "recipients"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    email: Mapped[str] = mapped_column(String(254))
    first_name: Mapped[str] = mapped_column(String(150))
    last_name: Mapped[str] = mapped_column(String(150), default="")


class OrderCustomer(Base):
    """Which customer an order belongs to. Payment and cancellation events carry only the order
    number, so this maps it back to a customer. Recorded from OrderPlaced."""

    __tablename__ = "order_customers"

    order_number: Mapped[str] = mapped_column(String(20), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)


class NotificationLog(Base):
    """One row per email actually sent. A failed send isn't logged: it is retried, then
    dead-lettered, and the dead-letter topic keeps the reason."""

    __tablename__ = "notification_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # The event that caused the email.
    message_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    kind: Mapped[str] = mapped_column(String(40))
    order_number: Mapped[str] = mapped_column(String(20), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProcessedMessage(Base):
    """Message ids already handled, so a redelivered message is skipped."""

    __tablename__ = "processed_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    topic: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(100))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

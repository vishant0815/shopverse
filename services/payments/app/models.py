import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Enum, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class PaymentStatus(str, enum.Enum):
    REQUIRES_PAYMENT = "requires_payment"   # created, waiting for the customer to pay
    SUCCEEDED = "succeeded"                 # provider confirmed and the order is marked paid
    FAILED = "failed"                       # last attempt failed; the customer can try again
    REFUND_REQUIRED = "refund_required"     # money taken but the order was cancelled meanwhile
    AMOUNT_MISMATCH = "amount_mismatch"     # provider amount didn't match; needs a human


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (CheckConstraint("amount_minor > 0", name="payment_amount_positive"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # One payment per order. A failed attempt is retried on the same payment.
    order_number: Mapped[str] = mapped_column(String(20), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    provider: Mapped[str] = mapped_column(String(20))
    provider_payment_id: Mapped[str] = mapped_column(String(100), unique=True)
    client_secret: Mapped[str] = mapped_column(String(255))
    # Stored in the smallest unit (pence), the way payment providers expect it.
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status", values_callable=lambda e: [m.value for m in e]),
        default=PaymentStatus.REQUIRES_PAYMENT,
    )
    last_error: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def amount(self) -> Decimal:
        return (Decimal(self.amount_minor) / 100).quantize(Decimal("0.01"))


class ProcessedEvent(Base):
    """Every provider event id we've handled. Providers deliver webhooks at least once,
    so the same event can arrive twice; this table makes handling it a no-op the second time."""

    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def to_minor_units(amount: Decimal) -> int:
    return int((Decimal(amount) * 100).quantize(Decimal("1")))


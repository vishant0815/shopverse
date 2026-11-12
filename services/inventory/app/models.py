import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .messaging import OutboxMessage, ProcessedMessage  # noqa: F401  (registers the tables)


class StockItem(Base):
    """Stock for one variant (one colour and size of a product).

    on_hand:  what's on the shelf.
    reserved: how many of those are held for checkouts that haven't been paid yet.
    available = on_hand - reserved: what a new customer can buy.
    """

    __tablename__ = "stock_items"
    __table_args__ = (
        CheckConstraint("on_hand >= 0", name="on_hand_not_negative"),
        CheckConstraint("reserved >= 0", name="reserved_not_negative"),
        # The database itself refuses to hold more than is on the shelf.
        CheckConstraint("reserved <= on_hand", name="reserved_within_on_hand"),
    )

    # Copied from the products service's catalogue events.
    variant_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    seller_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    sku: Mapped[str] = mapped_column(String(64))
    # False once the variant is removed from the catalogue; kept for past reservations.
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    on_hand: Mapped[int] = mapped_column(Integer, default=0)
    reserved: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def available(self) -> int:
        return max(self.on_hand - self.reserved, 0)


class ReservationStatus(str, enum.Enum):
    HELD = "held"            # items taken off sale for an unpaid order
    COMMITTED = "committed"  # the order was paid: the held items are sold
    RELEASED = "released"    # the hold (or sale) was undone and the items are back on sale
    REJECTED = "rejected"    # there wasn't enough stock; nothing was held


class Reservation(Base):
    """What one order holds. One per order, so a repeated command finds the earlier outcome."""

    __tablename__ = "reservations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    order_number: Mapped[str] = mapped_column(String(20), unique=True)
    status: Mapped[ReservationStatus] = mapped_column(
        Enum(ReservationStatus, name="reservation_status", values_callable=lambda e: [m.value for m in e])
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    lines: Mapped[list["ReservationLine"]] = relationship(
        back_populates="reservation", cascade="all, delete-orphan", order_by="ReservationLine.variant_id"
    )


class ReservationLine(Base):
    __tablename__ = "reservation_lines"
    __table_args__ = (CheckConstraint("quantity > 0", name="line_quantity_positive"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reservation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reservations.id", ondelete="CASCADE"), index=True)
    variant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    quantity: Mapped[int] = mapped_column(Integer)

    reservation: Mapped[Reservation] = relationship(back_populates="lines")

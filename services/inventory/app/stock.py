"""Stock logic: catalogue updates, and the reserve / commit / release commands.

Every function here runs inside the caller's transaction (the worker's, for messages)
and writes its replies to the outbox, so a change and its reply are saved together.
"""

import hashlib
import logging
import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .messaging import enqueue
from .models import Reservation, ReservationLine, ReservationStatus, StockItem

log = logging.getLogger("inventory")

EVENTS = "inventory.events"


def demo_quantity(variant_id: uuid.UUID) -> int:
    """Stable made-up stock for the demo shop: about 6% sold out, 9% running low."""
    n = int(hashlib.sha256(str(variant_id).encode()).hexdigest(), 16) % 100
    if n < 6:
        return 0
    if n < 15:
        return 1 + n % 4
    return 8 + n % 33


# Catalogue (from the products service) -------------------------------------------------

def variant_upserted(db: Session, message: dict) -> None:
    data = message["data"]
    variant_id = uuid.UUID(data["variant_id"])
    item = db.get(StockItem, variant_id, with_for_update=True)
    if item is None:
        on_hand = demo_quantity(variant_id) if get_settings().demo_stock else 0
        item = StockItem(variant_id=variant_id, on_hand=on_hand, reserved=0)
        db.add(item)
    item.product_id = uuid.UUID(data["product_id"])
    item.seller_id = uuid.UUID(data["seller_id"])
    item.sku = data["sku"]
    item.active = bool(data.get("active", True))


def variant_removed(db: Session, message: dict) -> None:
    item = db.get(StockItem, uuid.UUID(message["data"]["variant_id"]), with_for_update=True)
    if item is not None:
        item.active = False


# Commands (from the orders service's checkout saga) -------------------------------------

def _lock(db: Session, variant_ids) -> dict[uuid.UUID, StockItem]:
    """Lock stock rows in a fixed order (by id), so two checkouts can't deadlock."""
    rows = db.scalars(
        select(StockItem).where(StockItem.variant_id.in_(variant_ids)).order_by(StockItem.variant_id).with_for_update()
    ).all()
    return {row.variant_id: row for row in rows}


def _reply(db: Session, type_: str, order_number: str, **data) -> None:
    enqueue(db, EVENTS, type_, order_number, {"order_number": order_number, **data})


def _lines_out(reservation: Reservation) -> list[dict]:
    return [{"variant_id": str(line.variant_id), "quantity": line.quantity} for line in reservation.lines]


def _repeat_outcome(db: Session, reservation: Reservation) -> None:
    """The same command came again (the orchestrator retried): answer the same way."""
    if reservation.status == ReservationStatus.REJECTED:
        _reply(db, "StockRejected", reservation.order_number, unavailable=[])
    elif reservation.status == ReservationStatus.RELEASED:
        _reply(db, "StockReleased", reservation.order_number)
    else:
        _reply(db, "StockReserved", reservation.order_number, lines=_lines_out(reservation))


def reserve(db: Session, message: dict) -> None:
    data = message["data"]
    order_number = data["order_number"]
    existing = db.scalar(select(Reservation).where(Reservation.order_number == order_number).with_for_update())
    if existing:
        _repeat_outcome(db, existing)
        return

    wanted: dict[uuid.UUID, int] = defaultdict(int)
    for line in data["lines"]:
        wanted[uuid.UUID(line["variant_id"])] += int(line["quantity"])

    stock = _lock(db, wanted)
    unavailable = []
    for variant_id, quantity in wanted.items():
        item = stock.get(variant_id)
        available = item.available if item is not None and item.active else 0
        if available < quantity:
            unavailable.append({"variant_id": str(variant_id), "requested": quantity, "available": available})

    if unavailable:
        db.add(Reservation(order_number=order_number, status=ReservationStatus.REJECTED))
        _reply(db, "StockRejected", order_number, unavailable=unavailable)
        log.info("rejected %s: %s", order_number, unavailable)
        return

    reservation = Reservation(order_number=order_number, status=ReservationStatus.HELD)
    for variant_id, quantity in sorted(wanted.items()):
        stock[variant_id].reserved += quantity
        reservation.lines.append(ReservationLine(variant_id=variant_id, quantity=quantity))
    db.add(reservation)
    db.flush()
    _reply(db, "StockReserved", order_number, lines=_lines_out(reservation))


def _reservation(db: Session, order_number: str) -> Reservation | None:
    return db.scalar(select(Reservation).where(Reservation.order_number == order_number).with_for_update())


def commit(db: Session, message: dict) -> None:
    """The order was paid: held items become sold (they leave the shelf)."""
    order_number = message["data"]["order_number"]
    reservation = _reservation(db, order_number)
    if reservation is None or reservation.status != ReservationStatus.HELD:
        if reservation is not None and reservation.status == ReservationStatus.COMMITTED:
            _reply(db, "StockCommitted", order_number)  # repeated command
        else:
            log.error("can't commit %s: reservation is %s", order_number, reservation and reservation.status.value)
        return
    stock = _lock(db, [line.variant_id for line in reservation.lines])
    for line in reservation.lines:
        item = stock[line.variant_id]
        item.reserved -= line.quantity
        item.on_hand -= line.quantity
    reservation.status = ReservationStatus.COMMITTED
    _reply(db, "StockCommitted", order_number)


def release(db: Session, message: dict) -> None:
    """Undo a hold (items back on sale), or a sale that won't ship (items back on the shelf)."""
    order_number = message["data"]["order_number"]
    reservation = _reservation(db, order_number)
    if reservation is None or reservation.status in (ReservationStatus.REJECTED, ReservationStatus.RELEASED):
        # Nothing is held: never reserved, already released, or the release overtook
        # nothing. Answer anyway so the orchestrator can close its books.
        _reply(db, "StockReleased", order_number)
        return
    stock = _lock(db, [line.variant_id for line in reservation.lines])
    for line in reservation.lines:
        item = stock[line.variant_id]
        if reservation.status == ReservationStatus.HELD:
            item.reserved -= line.quantity
        else:  # committed: the sale is undone, so the items go back on the shelf
            item.on_hand += line.quantity
    reservation.status = ReservationStatus.RELEASED
    _reply(db, "StockReleased", order_number)


HANDLERS = {
    "VariantUpserted": variant_upserted,
    "VariantRemoved": variant_removed,
    "ReserveStock": reserve,
    "CommitStock": commit,
    "ReleaseStock": release,
}

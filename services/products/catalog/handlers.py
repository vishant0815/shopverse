"""Message handlers for this service's worker (see settings.MESSAGING and docs/events.md).

Each handler runs inside the same database transaction as the message's record of being
handled, so a message is applied once, or not at all.
"""

import uuid

from .events import announce_product
from .models import Product, SellerStatus


def seller_status_changed(envelope: dict) -> None:
    """users.events: a seller's shop was approved, suspended or is pending."""
    data = envelope["data"]
    status = data["status"]
    if status not in SellerStatus.Status.values:
        # Raised, so the worker retries and then dead-letters it, rather than guessing.
        raise ValueError(f"unknown seller status {status!r}")
    seller_id = uuid.UUID(data["seller_id"])
    SellerStatus.objects.update_or_create(seller_id=seller_id, defaults={"status": status})
    # Their listed products change with the status, so search needs each one's new state.
    for product_id in Product.objects.filter(seller_id=seller_id, status=Product.Status.ACTIVE).values_list("id", flat=True):
        announce_product(product_id)


HANDLERS = {
    "SellerStatusChanged": seller_status_changed,
}

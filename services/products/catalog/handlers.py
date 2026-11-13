"""Message handlers for this service's worker (see settings.MESSAGING and docs/events.md).

Each handler runs inside the same database transaction as the message's record of being
handled, so a message is applied once, or not at all.
"""

import uuid

from .models import SellerStatus


def seller_status_changed(envelope: dict) -> None:
    """users.events: a seller's shop was approved, suspended or is pending."""
    data = envelope["data"]
    status = data["status"]
    if status not in SellerStatus.Status.values:
        # Raised, so the worker retries and then dead-letters it, rather than guessing.
        raise ValueError(f"unknown seller status {status!r}")
    SellerStatus.objects.update_or_create(seller_id=uuid.UUID(data["seller_id"]), defaults={"status": status})


HANDLERS = {
    "SellerStatusChanged": seller_status_changed,
}

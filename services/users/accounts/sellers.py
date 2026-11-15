"""Seller accounts: creating a shop and changing its approval status.

Every status change is written to the outbox in the same transaction as the change, so
other services (products, for now) learn about it exactly when it happens, and never
about a change that rolled back. See docs/events.md.

Allowed moves:
- pending -> approved   (admin approves a new seller)
- suspended -> approved (admin reinstates a suspended seller)
- approved -> suspended (admin suspends a seller)
Anything else is refused, so an approval can't be repeated silently and a pending shop
can't be suspended before it was ever approved.
"""

from django.db import transaction

from messaging.kafka import enqueue

from .models import SellerProfile

SELLER_EVENTS_TOPIC = "users.events"
STATUS_CHANGED = "SellerStatusChanged"

ALLOWED_MOVES = {
    (SellerProfile.Status.PENDING, SellerProfile.Status.APPROVED),
    (SellerProfile.Status.SUSPENDED, SellerProfile.Status.APPROVED),
    (SellerProfile.Status.APPROVED, SellerProfile.Status.SUSPENDED),
}


class InvalidTransition(Exception):
    pass


def _announce(profile: SellerProfile) -> None:
    # The seller id is the user id, which is what the other services know the seller by.
    enqueue(SELLER_EVENTS_TOPIC, STATUS_CHANGED, str(profile.user_id), {
        "seller_id": str(profile.user_id),
        "status": profile.status,
    })


def create_seller_profile(user, shop_name: str) -> SellerProfile:
    """A new seller's shop starts pending until an admin approves it."""
    with transaction.atomic():
        profile = SellerProfile.objects.create(user=user, shop_name=shop_name)
        _announce(profile)
    return profile


def ensure_approved_shop(user, shop_name: str) -> SellerProfile:
    """Make sure a seller has an approved shop, for the demo seed. Only announces a change
    when there is one, so running the seed again doesn't repeat messages."""
    with transaction.atomic():
        profile = SellerProfile.objects.select_for_update().filter(user=user).first()
        if profile is None:
            profile = SellerProfile.objects.create(user=user, shop_name=shop_name, status=SellerProfile.Status.APPROVED)
            _announce(profile)
        elif profile.status != SellerProfile.Status.APPROVED:
            profile.status = SellerProfile.Status.APPROVED
            profile.save(update_fields=["status", "updated_at"])
            _announce(profile)
    return profile


def change_status(profile: SellerProfile, new_status: str) -> SellerProfile:
    """Move a shop to a new status, or raise InvalidTransition if that move isn't allowed."""
    with transaction.atomic():
        # Lock the row, so two admins clicking at once can't both see the old status.
        locked = SellerProfile.objects.select_for_update().get(pk=profile.pk)
        if (locked.status, new_status) not in ALLOWED_MOVES:
            raise InvalidTransition(f"A seller that is {locked.status} can't be changed to {new_status}.")
        locked.status = new_status
        locked.save(update_fields=["status", "updated_at"])
        _announce(locked)
    return locked

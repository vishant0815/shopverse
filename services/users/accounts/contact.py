"""Customer contact details, announced to the notifications service.

Notifications keeps its own copy of each customer's name and email, so it can send an email
without calling this service. It learns them from two messages on users.events:

- UserRegistered, when an account is created (signup, admin, seed command);
- UserContactChanged, when the email or name changes (profile edit or admin).

Both are written to the outbox in the same transaction as the change, the same way seller
status is announced (see docs/events.md). User.save() calls these, so every path is covered.
"""

from messaging.kafka import enqueue

USERS_EVENTS_TOPIC = "users.events"
REGISTERED = "UserRegistered"
CONTACT_CHANGED = "UserContactChanged"


def contact_data(user) -> dict:
    return {
        "user_id": str(user.id),
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
    }


def _announce(user, type_: str) -> None:
    # The user id is the key, so one customer's messages are read in the order they happened.
    enqueue(USERS_EVENTS_TOPIC, type_, str(user.id), contact_data(user))


def announce_registered(user) -> None:
    _announce(user, REGISTERED)


def announce_changed(user) -> None:
    _announce(user, CONTACT_CHANGED)

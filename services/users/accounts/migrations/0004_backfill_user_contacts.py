"""Existing customers get a UserRegistered message, so notifications learns their email.

Without it, anyone who signed up before the notifications service existed could never be
emailed about an order. Each user gets one message with their current contact details.
"""

import uuid

from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    OutboxMessage = apps.get_model("messaging", "OutboxMessage")

    for user in User.objects.iterator():
        user_id = str(user.id)
        message_id = uuid.uuid4()
        OutboxMessage.objects.create(
            message_id=message_id,
            topic="users.events",
            key=user_id,
            type="UserRegistered",
            payload={
                "id": str(message_id),
                "type": "UserRegistered",
                "source": "users",
                "occurred_at": timezone.now().isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "key": user_id,
                "data": {
                    "user_id": user_id,
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                },
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_backfill_seller_profiles"),
        ("messaging", "0001_initial"),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]

"""Existing sellers already trade, so their shops start approved.

Each one also gets a SellerStatusChanged message in the outbox. Without it the products
service would never hear that these sellers were approved, and would refuse their writes.
"""

import uuid

from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    SellerProfile = apps.get_model("accounts", "SellerProfile")
    OutboxMessage = apps.get_model("messaging", "OutboxMessage")

    for user in User.objects.filter(role="seller").iterator():
        if SellerProfile.objects.filter(user_id=user.id).exists():
            continue
        SellerProfile.objects.create(
            user=user,
            shop_name=f"{user.first_name}'s shop"[:120],
            status="approved",
        )
        seller_id = str(user.id)
        message_id = uuid.uuid4()
        OutboxMessage.objects.create(
            message_id=message_id,
            topic="users.events",
            key=seller_id,
            type="SellerStatusChanged",
            payload={
                "id": str(message_id),
                "type": "SellerStatusChanged",
                "source": "users",
                "occurred_at": timezone.now().isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "key": seller_id,
                "data": {"seller_id": seller_id, "status": "approved"},
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_seller_profile"),
        ("messaging", "0001_initial"),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]

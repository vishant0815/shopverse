"""Create the demo seller and admin accounts, so the seller and admin panels can be tried
straight after `docker compose up`.

    DEMO_USER_PASSWORD=... python manage.py seed_demo_users

The demo seller's id matches the seller id the product service gives its demo products,
so signing in as the demo seller shows those 12 products as "My products".
Safe to run again: existing accounts are kept and their password is updated to match.
"""

import os
import uuid

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User

# Must match DEMO_SELLER_ID in services/products/catalog/management/commands/seed_catalog.py
DEMO_SELLER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")

ACCOUNTS = [
    {"email": "seller@shopverse.dev", "first_name": "Sam", "last_name": "Seller", "role": User.Role.SELLER, "id": DEMO_SELLER_ID},
    {"email": "admin@shopverse.dev", "first_name": "Ada", "last_name": "Admin", "role": User.Role.ADMIN},
]


class Command(BaseCommand):
    help = "Create or update the demo seller and admin accounts."

    def handle(self, *args, **options):
        password = os.environ.get("DEMO_USER_PASSWORD", "")
        if not password or password.startswith("change-me"):
            raise CommandError("Set DEMO_USER_PASSWORD (python scripts/create_env.py generates one).")
        try:
            password_validation.validate_password(password)
        except ValidationError as error:
            raise CommandError(f"DEMO_USER_PASSWORD is too weak: {' '.join(error.messages)}")

        for account in ACCOUNTS:
            details = dict(account)
            email = details.pop("email")
            user = User.objects.filter(email=email).first()
            if user is None:
                is_admin = details["role"] == User.Role.ADMIN
                user = User(email=email, is_staff=is_admin, is_superuser=is_admin, **details)
                action = "Created"
            else:
                action = "Updated"
                for field in ("first_name", "last_name", "role"):
                    setattr(user, field, details[field])
            user.set_password(password)
            user.save()
            self.stdout.write(f"{action} {user.role} account {email}")

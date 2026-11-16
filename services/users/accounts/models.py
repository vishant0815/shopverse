import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models, transaction
from django.utils import timezone

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        SELLER = "seller", "Seller"
        ADMIN = "admin", "Admin"

    # UUIDs instead of sequential ids, so ids can't be guessed or counted
    # and are safe to share with other services in events.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["first_name"]

    class Meta:
        ordering = ["-date_joined"]
        indexes = [models.Index(fields=["role"])]

    def __str__(self):
        return self.email

    # The contact details other services keep a copy of (see accounts/contact.py).
    CONTACT_FIELDS = ("email", "first_name", "last_name")

    @classmethod
    def from_db(cls, db, field_names, values):
        user = super().from_db(db, field_names, values)
        user._contact_as_loaded = user._contact_values()
        return user

    def _contact_values(self):
        return tuple(getattr(self, field) for field in self.CONTACT_FIELDS)

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        # Imported here: the messaging app's models must not load while this module does.
        from .contact import announce_changed, announce_registered

        # The change and its announcement commit together, or not at all.
        with transaction.atomic():
            is_new = self._state.adding
            changed = not is_new and self._contact_values() != getattr(self, "_contact_as_loaded", None)
            super().save(*args, **kwargs)
            if is_new:
                announce_registered(self)
            elif changed:
                announce_changed(self)
            self._contact_as_loaded = self._contact_values()

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()


class Address(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="addresses")
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20)
    line1 = models.CharField(max_length=255)
    line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100)
    county = models.CharField(max_length=100, blank=True)
    postcode = models.CharField(max_length=20)
    country = models.CharField(max_length=2, default="GB")
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_default", "-created_at"]
        constraints = [
            # The database itself guarantees at most one default address per user.
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_default=True),
                name="one_default_address_per_user",
            )
        ]

    def __str__(self):
        return f"{self.full_name}, {self.line1}, {self.postcode}"

    def save(self, *args, **kwargs):
        with transaction.atomic():
            others = Address.objects.filter(user=self.user).exclude(pk=self.pk)
            if not others.exists():
                # A user's first address is always the default.
                self.is_default = True
            if self.is_default:
                others.filter(is_default=True).update(is_default=False)
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            was_default = self.is_default
            user = self.user
            result = super().delete(*args, **kwargs)
            if was_default:
                # Promote the newest remaining address so the user keeps a default.
                newest = Address.objects.filter(user=user).order_by("-created_at").first()
                if newest:
                    newest.is_default = True
                    newest.save(update_fields=["is_default", "updated_at"])
            return result


class SellerProfile(models.Model):
    """A seller's shop, and whether an admin has approved it to list products.

    Every status change is announced as a SellerStatusChanged event (see
    accounts/sellers.py), so other services can keep their own copy of the status.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending approval"
        APPROVED = "approved", "Approved"
        SUSPENDED = "suspended", "Suspended"

    # Keyed by the user, so a seller has one shop and the seller id is the user id.
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="seller_profile")
    shop_name = models.CharField(max_length=120)
    description = models.TextField(max_length=1000, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status"])]

    def __str__(self):
        return f"{self.shop_name} ({self.status})"

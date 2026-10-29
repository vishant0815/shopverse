import secrets
import string
import uuid
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class Cart(models.Model):
    """One cart per user. It stores only what was chosen and how many;
    prices are looked up live from the product service every time."""

    user_id = models.UUIDField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart of {self.user_id}"


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    variant_id = models.UUIDField()
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["added_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["cart", "variant_id"], name="one_line_per_variant"),
            models.CheckConstraint(condition=models.Q(quantity__gte=1), name="cart_quantity_positive"),
        ]


def generate_order_number():
    """Short, readable and hard to guess: SV-20261029-K7Q2ZP."""
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(6))
    return f"SV-{timezone.now():%Y%m%d}-{suffix}"


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "Pending payment"
        PAID = "paid", "Paid"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"

    # The only moves an order can make. Anything else is rejected.
    TRANSITIONS = {
        Status.PENDING_PAYMENT: {Status.PAID, Status.CANCELLED},
        Status.PAID: {Status.SHIPPED, Status.CANCELLED},
        Status.SHIPPED: {Status.DELIVERED},
        Status.DELIVERED: set(),
        Status.CANCELLED: set(),
    }
    CUSTOMER_CANCELLABLE = {Status.PENDING_PAYMENT, Status.PAID}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=20, unique=True, default=generate_order_number, editable=False)
    user_id = models.UUIDField(db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_PAYMENT)
    currency = models.CharField(max_length=3, default="GBP")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    shipping_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2)
    # A copy of the address at the time of ordering. If the user edits or deletes
    # the address later, this order still shows where it was sent.
    shipping_address = models.JSONField()
    # Sent by the client as the Idempotency-Key header, so a double-click or a
    # retried request can never create two orders.
    idempotency_key = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user_id", "-created_at"]), models.Index(fields=["status"])]
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="unique_idempotency_key_per_user",
            ),
            models.CheckConstraint(
                condition=models.Q(total=models.F("subtotal") + models.F("shipping_fee")),
                name="order_total_matches_parts",
            ),
        ]

    def __str__(self):
        return self.number

    def can_move_to(self, new_status):
        return new_status in self.TRANSITIONS[self.status]

    def move_to(self, new_status, changed_by, note=""):
        """Change status and record who did it. Callers check can_move_to first."""
        old_status = self.status
        self.status = new_status
        self.save(update_fields=["status", "updated_at"])
        OrderStatusHistory.objects.create(
            order=self, from_status=old_status, to_status=new_status, changed_by=changed_by, note=note
        )


class OrderItem(models.Model):
    """A snapshot of what was bought. Names and prices are copied, not referenced,
    so later catalogue changes never rewrite an old order."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    variant_id = models.UUIDField()
    product_id = models.UUIDField()
    seller_id = models.UUIDField(db_index=True)
    sku = models.CharField(max_length=64)
    product_name = models.CharField(max_length=200)
    product_slug = models.CharField(max_length=220)
    colour = models.CharField(max_length=50, blank=True)
    size = models.CharField(max_length=20, blank=True)
    thumbnail = models.URLField(max_length=500, blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField()
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gte=1), name="order_quantity_positive"),
            models.CheckConstraint(
                condition=models.Q(line_total=models.F("unit_price") * models.F("quantity")),
                name="line_total_matches_parts",
            ),
        ]


class OrderStatusHistory(models.Model):
    """Audit trail: every status change, who made it and when."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="history")
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    changed_by = models.UUIDField(null=True)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name_plural = "order status history"

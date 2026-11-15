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
    # The code the customer applied. Checked again at every read and at checkout, so an
    # expired or used-up code stops working even if it was applied earlier.
    coupon_code = models.CharField(max_length=40, blank=True)
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


class Coupon(models.Model):
    """A discount code that admins create. It takes money off the basket subtotal.

    Shipping is decided before the discount (see pricing.totals_for), so a code never
    adds a shipping fee. Uses are not stored on the coupon: they are counted from the
    orders that carry the code (see coupons.py), so a cancelled order frees its use.
    """

    class Kind(models.TextChoices):
        PERCENT = "percent", "Percent off"
        FIXED = "fixed", "Fixed amount off"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Always stored in capitals, so "welcome10" and "WELCOME10" are the same code.
    code = models.CharField(max_length=40, unique=True)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    value = models.DecimalField(max_digits=10, decimal_places=2)
    min_subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    usage_limit = models.PositiveIntegerField(null=True, blank=True)
    per_customer_limit = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(kind="percent", value__gte=1, value__lte=100)
                    | models.Q(kind="fixed", value__gt=0)
                ),
                name="coupon_value_valid",
            ),
            models.CheckConstraint(condition=models.Q(min_subtotal__gte=0), name="coupon_min_subtotal_not_negative"),
            models.CheckConstraint(
                condition=models.Q(starts_at__isnull=True)
                | models.Q(ends_at__isnull=True)
                | models.Q(ends_at__gt=models.F("starts_at")),
                name="coupon_ends_after_start",
            ),
            models.CheckConstraint(
                condition=models.Q(usage_limit__isnull=True) | models.Q(usage_limit__gte=1),
                name="coupon_usage_limit_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(per_customer_limit__isnull=True) | models.Q(per_customer_limit__gte=1),
                name="coupon_per_customer_limit_positive",
            ),
        ]

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)


def generate_order_number():
    """Short, readable and hard to guess: SV-20261029-K7Q2ZP."""
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(6))
    return f"SV-{timezone.now():%Y%m%d}-{suffix}"


class Order(models.Model):
    class Status(models.TextChoices):
        RESERVING = "reserving", "Checking stock"
        PENDING_PAYMENT = "pending_payment", "Pending payment"
        PAID = "paid", "Paid"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"

    # The only moves an order can make. Anything else is rejected.
    TRANSITIONS = {
        Status.RESERVING: {Status.PENDING_PAYMENT, Status.CANCELLED},
        Status.PENDING_PAYMENT: {Status.PAID, Status.CANCELLED},
        Status.PAID: {Status.SHIPPED, Status.CANCELLED},
        Status.SHIPPED: {Status.DELIVERED},
        Status.DELIVERED: set(),
        Status.CANCELLED: set(),
    }
    CUSTOMER_CANCELLABLE = {Status.RESERVING, Status.PENDING_PAYMENT, Status.PAID}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=20, unique=True, default=generate_order_number, editable=False)
    user_id = models.UUIDField(db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_PAYMENT)
    currency = models.CharField(max_length=3, default="GBP")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    # What the coupon took off the subtotal, copied here so the order keeps showing it
    # even if the coupon is later edited or deleted.
    coupon_code = models.CharField(max_length=40, blank=True, db_index=True)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
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
                condition=models.Q(
                    total=models.F("subtotal") - models.F("discount_amount") + models.F("shipping_fee")
                ),
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

    def add_note(self, note, changed_by=None):
        """Record something that happened without a status change (a refund, say)."""
        OrderStatusHistory.objects.create(
            order=self, from_status=self.status, to_status=self.status, changed_by=changed_by, note=note
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
    # The flash sale item this line bought at its sale price, if any. Sold-unit caps count these lines.
    flash_sale_item_id = models.UUIDField(null=True, blank=True, db_index=True)

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


class CheckoutSaga(models.Model):
    """The state of an order's checkout saga (see ordering/saga.py and docs/events.md).

    Orders is the orchestrator: it asks inventory to hold the items, waits for the
    payment, then either confirms the sale or undoes whatever was done so far.
    """

    class State(models.TextChoices):
        RESERVING = "reserving", "Waiting for inventory to hold the items"
        AWAITING_PAYMENT = "awaiting_payment", "Items held, waiting for payment"
        COMPLETED = "completed", "Paid and the sale confirmed"
        FAILED = "failed", "Stock couldn't be held"
        CANCELLED = "cancelled", "Cancelled and compensated"

    class CancelCode(models.TextChoices):
        SOLD_OUT = "sold_out"
        NOT_PAID_IN_TIME = "not_paid_in_time"
        STOCK_CHECK_TIMEOUT = "stock_check_timeout"
        CUSTOMER = "customer"
        ADMIN = "admin"

    class RefundStatus(models.TextChoices):
        REQUESTED = "requested"
        REFUNDED = "refunded"
        FAILED = "failed"

    order = models.OneToOneField(Order, on_delete=models.CASCADE, primary_key=True, related_name="saga")
    state = models.CharField(max_length=20, choices=State.choices, default=State.RESERVING)
    hold_expires_at = models.DateTimeField(null=True, blank=True)
    cancel_code = models.CharField(max_length=30, choices=CancelCode.choices, blank=True)
    # What the customer is told, e.g. which item sold out.
    cancel_detail = models.CharField(max_length=500, blank=True)
    payment_id = models.CharField(max_length=100, blank=True)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    refund_status = models.CharField(max_length=20, choices=RefundStatus.choices, blank=True)
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            # The timeout sweep looks for holds that ran out and checks that hung.
            models.Index(fields=["state", "hold_expires_at"]),
            models.Index(fields=["state", "started_at"]),
        ]

    def __str__(self):
        return f"{self.order_id}: {self.state}"

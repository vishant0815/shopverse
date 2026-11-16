"""Coupon codes: what a code is worth, whether it can be used now, and how uses are counted.

A use is an order that carries the code and hasn't been cancelled. Counting from the orders
themselves means there's no counter to keep in step: cancelling an order gives its use back.

Checkout locks the coupon row (see evaluate) before it counts, so two customers can't both
take the last use of a code.
"""

from django.db.models import Count, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import Coupon, Order
from .pricing import money


class CouponError(Exception):
    """A code can't be used right now. `code` says why, `message` is for the customer."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def normalise(code):
    return (code or "").strip().upper()


def live_orders(code):
    return Order.objects.filter(coupon_code=code).exclude(status=Order.Status.CANCELLED)


def usage(code, user_id):
    """How many times a code has been used: (by everyone, by this customer)."""
    counts = live_orders(code).aggregate(
        everyone=Count("id"),
        mine=Count("id", filter=Q(user_id=user_id)),
    )
    return counts["everyone"], counts["mine"]


def discount_for(coupon, subtotal):
    """What the code takes off a subtotal. A fixed amount never takes more than the subtotal."""
    if coupon.kind == Coupon.Kind.PERCENT:
        return money(subtotal * coupon.value / 100)
    return min(money(coupon.value), subtotal)


def check(coupon, subtotal, user_id, now=None):
    """Raise CouponError, with the reason, if the code can't be used for this basket now.

    The minimum is compared with the subtotal before the discount.
    """
    now = now or timezone.now()
    if not coupon.is_active:
        raise CouponError("coupon_inactive", "This code is no longer active.")
    if coupon.starts_at and now < coupon.starts_at:
        raise CouponError("coupon_not_started", "This code isn't valid yet.")
    if coupon.ends_at and now >= coupon.ends_at:
        raise CouponError("coupon_expired", "This code has expired.")
    if subtotal < coupon.min_subtotal:
        raise CouponError(
            "coupon_min_not_met",
            f"Spend at least £{coupon.min_subtotal} before the discount to use this code.",
        )
    everyone, mine = usage(coupon.code, user_id)
    if coupon.usage_limit is not None and everyone >= coupon.usage_limit:
        raise CouponError("coupon_used_up", "This code has been used up.")
    if coupon.per_customer_limit is not None and mine >= coupon.per_customer_limit:
        raise CouponError("coupon_already_used", "You've already used this code.")


def evaluate(code, subtotal, user_id, *, lock=False):
    """The coupon a basket can use right now, or None when no code is set.

    With lock=True the coupon row stays locked until the surrounding transaction ends, so
    the usage count in check() can't change under a concurrent checkout. Call it inside
    transaction.atomic() when locking.
    """
    code = normalise(code)
    if not code:
        return None
    queryset = Coupon.objects.select_for_update() if lock else Coupon.objects.all()
    try:
        coupon = queryset.get(code=code)
    except Coupon.DoesNotExist:
        raise CouponError("coupon_not_found", "That code isn't valid.")
    check(coupon, subtotal, user_id)
    return coupon


def with_used_count():
    """Every coupon, with how many live orders have used it. For the admin list."""
    uses = (
        Order.objects.filter(coupon_code=OuterRef("code"))
        .exclude(status=Order.Status.CANCELLED)
        .order_by()
        .values("coupon_code")
        .annotate(n=Count("id"))
        .values("n")
    )
    return Coupon.objects.annotate(
        used_count=Coalesce(Subquery(uses, output_field=IntegerField()), Value(0)),
    )

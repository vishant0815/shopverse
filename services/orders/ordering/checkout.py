"""Turning a cart into an order.

The product service is called *before* any database lock is taken, so a slow catalogue
never holds rows locked. Inside the transaction the cart is locked and re-read; if it
changed while prices were being fetched, checkout stops and asks the client to retry.
"""

from django.conf import settings
from django.db import IntegrityError, transaction

from . import catalog
from .models import Cart, Order, OrderItem, OrderStatusHistory
from .pricing import price_lines, totals_for


class CheckoutError(Exception):
    def __init__(self, code, message, status=409, **extra):
        super().__init__(message)
        self.code, self.message, self.status, self.extra = code, message, status, extra

    def as_response_data(self):
        return {"code": self.code, "detail": self.message, **self.extra}


def snapshot(cart):
    return sorted((str(i.variant_id), i.quantity) for i in cart.items.all())


def place_order(user_id, shipping_address, idempotency_key="", expected_total=None):
    """Returns (order, created). created is False when the idempotency key was seen before."""
    if idempotency_key:
        existing = Order.objects.filter(user_id=user_id, idempotency_key=idempotency_key).first()
        if existing:
            return existing, False

    cart = Cart.objects.filter(user_id=user_id).first()
    if cart is None or not cart.items.exists():
        raise CheckoutError("cart_empty", "Your cart is empty.", status=400)

    # 1. Price the cart from the catalogue (no locks held).
    priced_snapshot = snapshot(cart)
    try:
        variants = catalog.lookup_variants([variant_id for variant_id, _ in priced_snapshot])
    except catalog.CatalogUnavailable:
        raise CheckoutError("catalog_unavailable", "Prices can't be checked right now. Please try again.", status=503)

    # 2. Lock the cart, make sure it hasn't changed, and create the order atomically.
    try:
        with transaction.atomic():
            cart = Cart.objects.select_for_update().get(pk=cart.pk)
            # A duplicate request may have been waiting on this lock while the first one
            # placed the order. Check again now that we hold the lock.
            if idempotency_key:
                existing = Order.objects.filter(user_id=user_id, idempotency_key=idempotency_key).first()
                if existing:
                    return existing, False
            if snapshot(cart) != priced_snapshot:
                raise CheckoutError("cart_changed", "Your cart changed during checkout. Please try again.")

            items = list(cart.items.all())
            lines, unavailable = price_lines(items, variants)
            if unavailable:
                raise CheckoutError(
                    "items_unavailable",
                    "Some items are no longer available. Remove them and try again.",
                    unavailable_variant_ids=unavailable,
                )

            totals = totals_for(lines)
            if expected_total is not None and expected_total != totals["total"]:
                raise CheckoutError(
                    "price_changed",
                    "Prices changed since you last looked. Please review your cart.",
                    expected_total=str(expected_total),
                    actual_total=str(totals["total"]),
                )

            order = Order.objects.create(
                user_id=user_id,
                currency=settings.CURRENCY,
                shipping_address=shipping_address,
                idempotency_key=idempotency_key,
                **totals,
            )
            OrderItem.objects.bulk_create([
                OrderItem(
                    order=order,
                    variant_id=line["item"].variant_id,
                    product_id=line["info"]["product_id"],
                    seller_id=line["info"]["seller_id"],
                    sku=line["info"]["sku"],
                    product_name=line["info"]["product_name"],
                    product_slug=line["info"]["product_slug"],
                    colour=line["info"].get("colour") or "",
                    size=line["info"].get("size") or "",
                    thumbnail=line["info"].get("thumbnail") or "",
                    unit_price=line["unit_price"],
                    quantity=line["item"].quantity,
                    line_total=line["line_total"],
                )
                for line in lines
            ])
            OrderStatusHistory.objects.create(
                order=order, from_status="", to_status=order.status, changed_by=user_id, note="Order placed"
            )
            cart.items.all().delete()
    except IntegrityError:
        # Two requests with the same idempotency key raced each other; the other one won.
        if idempotency_key:
            existing = Order.objects.filter(user_id=user_id, idempotency_key=idempotency_key).first()
            if existing:
                return existing, False
        raise

    return order, True

"""Flash sales: which variants are on sale right now, and whether a new sale would clash with another.

This module decides prices only. How many units of a sale have been sold is the orders
service's to count, because orders are where units are actually taken."""

from django.utils import timezone

from .models import FlashSaleItem


def running_items(variant_ids, now=None):
    """Return {variant_id (str): FlashSaleItem} for every variant whose sale is running at `now`.

    A variant can be in at most one running sale: overlapping windows are refused on save."""
    now = now or timezone.now()
    items = (
        FlashSaleItem.objects.filter(
            variant_id__in=list(variant_ids),
            sale__is_active=True,
            sale__starts_at__lte=now,
            sale__ends_at__gt=now,
        )
        .select_related("sale")
    )
    return {str(item.variant_id): item for item in items}


def clashing_items(variant_id, starts_at, ends_at, exclude_sale_id=None):
    """Active sale items for this variant whose window overlaps [starts_at, ends_at)."""
    clashes = FlashSaleItem.objects.filter(
        variant_id=variant_id,
        sale__is_active=True,
        sale__starts_at__lt=ends_at,
        sale__ends_at__gt=starts_at,
    )
    if exclude_sale_id is not None:
        clashes = clashes.exclude(sale_id=exclude_sale_id)
    return clashes


def flash_sale_payload(item):
    """The sale as the storefront and the orders service read it, or None when there is no sale."""
    if item is None:
        return None
    return {
        "item_id": str(item.id),
        "sale_id": str(item.sale_id),
        "name": item.sale.name,
        "sale_price": f"{item.sale_price:.2f}",
        "quantity_cap": item.quantity_cap,
        "ends_at": item.sale.ends_at.isoformat(),
    }

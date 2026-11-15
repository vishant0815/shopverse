"""Flash sale caps: how many units of a sale item are still open to buy at its sale price.

Units are counted from live orders, so a cancelled order gives its units back. Two checkouts for the
same sale item must not both read the same remaining count, so each takes a transaction-scoped
Postgres advisory lock on that item first. The lock is released when the checkout's transaction ends."""

from django.db import connection
from django.db.models import Sum

from .models import Order, OrderItem


def lock(flash_sale_item_id):
    """Hold the sale item for the rest of the current transaction. Must be called inside one."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [str(flash_sale_item_id)])


def sold_units(flash_sale_item_ids):
    """{item_id (str): units sold} across live orders, for every id asked about (zero when none)."""
    ids = [str(i) for i in flash_sale_item_ids]
    totals = (
        OrderItem.objects.filter(flash_sale_item_id__in=ids)
        .exclude(order__status=Order.Status.CANCELLED)
        .values("flash_sale_item_id")
        .annotate(total=Sum("quantity"))
    )
    counted = {str(row["flash_sale_item_id"]): row["total"] for row in totals}
    return {item_id: counted.get(item_id, 0) for item_id in ids}


def remaining_units(sale):
    """Units still open at the sale price, given the sale payload from the products service. None means no cap."""
    if not sale.get("quantity_cap"):
        return None
    sold = sold_units([sale["item_id"]])[str(sale["item_id"])]
    return max(sale["quantity_cap"] - sold, 0)

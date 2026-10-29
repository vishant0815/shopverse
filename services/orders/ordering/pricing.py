"""All money maths lives here, using Decimal (never float) and rounding to pennies."""

from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings

PENNY = Decimal("0.01")


def money(value):
    return Decimal(value).quantize(PENNY, rounding=ROUND_HALF_UP)


def shipping_for(subtotal):
    if subtotal <= 0 or subtotal >= settings.FREE_SHIPPING_THRESHOLD:
        return money(0)
    return money(settings.SHIPPING_FEE)


def price_lines(cart_items, variants):
    """Combine cart lines with live catalogue data.

    Returns (lines, unavailable): lines carry live prices and totals;
    unavailable lists the variant ids that can no longer be bought.
    """
    lines, unavailable = [], []
    for item in cart_items:
        info = variants.get(str(item.variant_id))
        if info is None:
            unavailable.append(str(item.variant_id))
            continue
        unit_price = money(info["price"])
        lines.append({"item": item, "info": info, "unit_price": unit_price, "line_total": money(unit_price * item.quantity)})
    return lines, unavailable


def totals_for(lines):
    subtotal = money(sum((line["line_total"] for line in lines), Decimal(0)))
    shipping = shipping_for(subtotal)
    return {"subtotal": subtotal, "shipping_fee": shipping, "total": money(subtotal + shipping)}

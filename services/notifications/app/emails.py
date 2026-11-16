"""The five customer emails. The plain-text and HTML versions are built from the same facts,
and every value from an event is escaped before it reaches the HTML.

Copy follows what the events actually say. The events carry no hold time and no delivery
address, so the emails say "within N minutes" and link to the order page for the address.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html import escape

SYMBOLS = {"GBP": "£", "EUR": "€", "USD": "$"}

# Cancellation reasons from the orders service, with what the customer needs to know.
# Each entry: (sentence, whether the customer was charged). None means it isn't known.
CANCEL_REASONS = {
    "not_paid_in_time": ("Payment wasn't received within the time allowed, so the items went back on sale.", False),
    "sold_out": ("An item sold out before payment, so the order couldn't be completed.", False),
    "stock_check_timeout": ("We couldn't confirm stock in time, so the order was cancelled.", False),
    "customer": ("You cancelled this order.", None),
    "admin": ("Shopverse cancelled this order.", None),
}
UNPAID_LINE = "You haven't been charged."
PAID_LINE = "If you had paid, your refund follows in a separate email."

# Refund reasons from the payments service (the cancellation or mismatch that caused it).
REFUND_REASONS = {
    "customer": "You cancelled this order after paying.",
    "admin": "Shopverse cancelled this order after payment.",
    "order_cancelled": "The order was cancelled, so the payment was returned.",
    "amount_mismatch": "The payment didn't match the order total, so it was returned.",
}

DEFAULT_REFUND_REASON = "The payment for this order was returned."


@dataclass(frozen=True)
class Email:
    subject: str
    text: str
    html: str


def money(amount: str, currency: str) -> str:
    """'83.00', 'GBP' -> '£83.00'. Falls back to the raw values rather than failing a send."""
    try:
        value = Decimal(amount)
    except (InvalidOperation, TypeError):
        return f"{amount} {currency}".strip()
    text = f"{value:,.2f}"
    symbol = SYMBOLS.get(currency)
    return f"{symbol}{text}" if symbol else f"{text} {currency}".strip()


def item_lines(items: list[dict], currency: str) -> list[tuple[str, str]]:
    """(label, amount) pairs, one per line bought."""
    rows = []
    for item in items:
        detail = ", ".join(part for part in (item.get("colour"), item.get("size")) if part)
        name = f"{item['name']}, {detail}" if detail else item["name"]
        label = f"{name} × {item['quantity']}"
        rows.append((label, money(item["line_total"], currency)))
    return rows


def _order_url(site_url: str, order_number: str) -> str:
    return f"{site_url.rstrip('/')}/orders/{order_number}"


def _render(*, subject: str, heading: str, first_name: str, paragraphs: list[str],
            order_number: str, action: tuple[str, str], rows: list[tuple[str, str]] = (),
            total: tuple[str, str] | None = None, accent: str = "#1B1F24") -> Email:
    greeting = f"Hi {first_name}," if first_name else "Hi there,"
    footer = (f"Order {order_number}. You're getting this because you placed an order with Shopverse.")
    label, url = action

    text_lines = [heading, "", greeting, "", *paragraphs]
    if rows:
        text_lines += [""] + [f"{label_} — {amount}" for label_, amount in rows]
    if total:
        text_lines += [f"{total[0]}: {total[1]}"]
    text_lines += ["", f"{label}: {url}", "", footer]
    text = "\n".join(text_lines)

    row_html = "".join(
        f'<div style="display:flex;justify-content:space-between;padding:10px 0;'
        f'border-bottom:1px solid #E3E6EA;font-size:14px"><span>{escape(label_)}</span>'
        f"<span>{escape(amount)}</span></div>"
        for label_, amount in rows
    )
    total_html = ""
    if total:
        total_html = (
            '<div style="display:flex;justify-content:space-between;padding:12px 0;font-size:15px;'
            f'font-weight:700"><span>{escape(total[0])}</span><span>{escape(total[1])}</span></div>'
        )
    body = "".join(f'<p style="margin:0;font-size:15px;line-height:1.5">{escape(p)}</p>' for p in paragraphs)
    html = (
        '<!doctype html><html lang="en"><body style="margin:0;background:#F4F5F7;padding:32px;'
        'font-family:Inter,system-ui,sans-serif;color:#1B1F24">'
        '<div style="background:#FFFFFF;border-radius:8px;max-width:576px;margin:0 auto;padding:32px;'
        'display:flex;flex-direction:column;gap:18px">'
        f'<div style="font-size:24px;font-weight:700;color:{accent}">{escape(heading)}</div>'
        f'<p style="margin:0;font-size:15px;line-height:1.5">{escape(greeting)}</p>'
        f"{body}"
        f'<div style="border-top:1px solid #E3E6EA">{row_html}{total_html}</div>'
        f'<div><a href="{escape(url, quote=True)}" style="display:inline-block;background:#2952CC;'
        'color:#FFFFFF;text-decoration:none;font-weight:600;font-size:15px;padding:12px 20px;'
        f'border-radius:6px">{escape(label)}</a></div>'
        f'<div style="font-size:12px;color:#5B6470;line-height:1.5">{escape(footer)}</div>'
        "</div></body></html>"
    )
    return Email(subject=subject, text=text, html=html)


def order_placed(*, first_name: str, order_number: str, items: list[dict], total: str, currency: str,
                 window_minutes: int, site_url: str) -> Email:
    return _render(
        subject=f"Complete your order {order_number} within {window_minutes} minutes",
        heading="We're holding your items",
        first_name=first_name,
        paragraphs=[
            f"Pay within {window_minutes} minutes to keep them. If payment isn't received in time, "
            "the order is cancelled and the items go back on sale.",
        ],
        order_number=order_number,
        action=("Pay now", _order_url(site_url, order_number)),
        rows=item_lines(items, currency),
        total=("Total", money(total, currency)),
    )


def order_confirmed(*, first_name: str, order_number: str, items: list[dict], total: str, currency: str,
                    site_url: str) -> Email:
    return _render(
        subject=f"Payment received for order {order_number}",
        heading="Thanks, your order is confirmed",
        first_name=first_name,
        paragraphs=[
            f"We've received your payment of {money(total, currency)}. You can follow your order on its page.",
        ],
        order_number=order_number,
        action=("View order", _order_url(site_url, order_number)),
        rows=item_lines(items, currency),
        total=("Total paid", money(total, currency)),
    )


def order_cancelled(*, first_name: str, order_number: str, reason: str, site_url: str) -> Email:
    sentence, charged = CANCEL_REASONS.get(reason, ("The order was cancelled.", None))
    paragraphs = [sentence]
    if charged is False:
        paragraphs.append(UNPAID_LINE)
    elif charged is None and reason in ("customer", "admin"):
        paragraphs.append(PAID_LINE)
    return _render(
        subject=f"Order {order_number} was cancelled",
        heading="Your order was cancelled",
        first_name=first_name,
        paragraphs=paragraphs,
        order_number=order_number,
        action=("Shop again", site_url.rstrip("/") + "/"),
    )


def payment_failed(*, first_name: str, order_number: str, site_url: str) -> Email:
    return _render(
        subject=f"Your payment for {order_number} didn't go through",
        heading="Your payment didn't go through",
        first_name=first_name,
        paragraphs=[
            f"The payment provider didn't accept your payment for order {order_number}. Try again now. "
            "If the order isn't paid in time, it is cancelled and the items go back on sale.",
        ],
        order_number=order_number,
        action=("Try payment again", _order_url(site_url, order_number)),
        accent="#B42318",
    )


def refund_issued(*, first_name: str, order_number: str, amount: str, currency: str, reason: str,
                  site_url: str) -> Email:
    reason_line = REFUND_REASONS.get(reason, DEFAULT_REFUND_REASON)
    return _render(
        subject=f"We've refunded {money(amount, currency)} for order {order_number}",
        heading="Your refund is on its way",
        first_name=first_name,
        paragraphs=[
            f"We've refunded {money(amount, currency)} for order {order_number} to the payment method you used. "
            "Your bank may take a few working days to show it.",
            reason_line,
        ],
        order_number=order_number,
        action=("View order", _order_url(site_url, order_number)),
        total=("Refunded", money(amount, currency)),
    )

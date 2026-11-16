"""The email copy: what each email says, in both its plain-text and HTML versions."""

from app import emails

SITE = "http://shop.test"
ITEMS = [
    {"name": "Trail running shoes", "colour": "Black", "size": "UK 9", "quantity": 1,
     "unit_price": "64.00", "line_total": "64.00"},
    {"name": "Cotton socks, 3-pack", "colour": "", "size": "", "quantity": 2,
     "unit_price": "9.50", "line_total": "19.00"},
]


def test_money_is_pounds_with_two_decimals_and_falls_back_safely():
    assert emails.money("83.00", "GBP") == "£83.00"
    assert emails.money("1234.5", "GBP") == "£1,234.50"
    assert emails.money("10.00", "JPY") == "10.00 JPY"
    assert emails.money("not-a-number", "GBP") == "not-a-number GBP"


def test_order_placed_lists_each_item_and_says_how_long_to_pay():
    email = emails.order_placed(
        first_name="Nia", order_number="SV-1", items=ITEMS, total="83.00", currency="GBP",
        window_minutes=15, site_url=SITE,
    )

    assert email.subject == "Complete your order SV-1 within 15 minutes"
    assert "Trail running shoes, Black, UK 9 × 1 — £64.00" in email.text
    assert "Cotton socks, 3-pack × 2 — £19.00" in email.text
    assert "Total: £83.00" in email.text
    assert f"Pay now: {SITE}/orders/SV-1" in email.text


def test_order_confirmed_says_what_was_paid_and_links_to_the_order():
    email = emails.order_confirmed(
        first_name="Nia", order_number="SV-2", items=ITEMS, total="83.00", currency="GBP", site_url=SITE,
    )

    assert email.subject == "Payment received for order SV-2"
    assert "We've received your payment of £83.00" in email.text
    assert "Total paid: £83.00" in email.text
    # No promise of a shipping email: the events have no shipping step.
    assert "ships" not in email.text


def test_an_unpaid_cancellation_says_the_customer_was_not_charged():
    email = emails.order_cancelled(first_name="Nia", order_number="SV-3", reason="not_paid_in_time", site_url=SITE)

    assert "Payment wasn't received within the time allowed" in email.text
    assert "You haven't been charged." in email.text


def test_a_customer_cancelling_after_paying_is_told_a_refund_follows():
    email = emails.order_cancelled(first_name="Nia", order_number="SV-4", reason="customer", site_url=SITE)

    assert "You cancelled this order." in email.text
    assert "your refund follows in a separate email" in email.text
    assert "haven't been charged" not in email.text


def test_an_unknown_cancellation_reason_says_nothing_about_money():
    email = emails.order_cancelled(first_name="Nia", order_number="SV-5", reason="something_new", site_url=SITE)

    assert "The order was cancelled." in email.text
    assert "charged" not in email.text
    assert "refund" not in email.text


def test_payment_failed_points_at_the_order_and_keeps_provider_errors_out():
    email = emails.payment_failed(first_name="Nia", order_number="SV-6", site_url=SITE)

    assert email.subject == "Your payment for SV-6 didn't go through"
    assert "Try again now" in email.text
    assert f"{SITE}/orders/SV-6" in email.text


def test_a_refund_names_the_amount_and_the_reason():
    email = emails.refund_issued(
        first_name="Nia", order_number="SV-7", amount="83.00", currency="GBP", reason="amount_mismatch",
        site_url=SITE,
    )

    assert email.subject == "We've refunded £83.00 for order SV-7"
    assert "The payment didn't match the order total, so it was returned." in email.text
    assert "£83.00" in email.html


def test_text_and_html_carry_the_same_order_number_and_total():
    email = emails.order_confirmed(
        first_name="Nia", order_number="SV-8", items=ITEMS, total="83.00", currency="GBP", site_url=SITE,
    )

    for needle in ("SV-8", "£83.00", "Trail running shoes"):
        assert needle in email.text
        assert needle in email.html


def test_values_from_events_are_escaped_in_html_but_not_in_text():
    hostile = [{"name": "<script>alert(1)</script>", "colour": "", "size": "", "quantity": 1,
                "unit_price": "1.00", "line_total": "1.00"}]
    email = emails.order_confirmed(
        first_name="<b>Nia</b>", order_number="SV-9", items=hostile, total="1.00", currency="GBP", site_url=SITE,
    )

    assert "<script>" not in email.html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in email.html
    assert "<b>Nia</b>" not in email.html
    assert "<script>alert(1)</script>" in email.text

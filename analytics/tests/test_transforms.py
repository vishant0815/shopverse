import uuid

from clickstream.transforms import activity, parse_clicks, parse_purchases, product_totals, search_terms

from .conftest import click, order_confirmed, order_placed

P1 = str(uuid.uuid4())
P2 = str(uuid.uuid4())
T0 = "2026-11-18T12:00:00Z"


def messages(spark, lines):
    return spark.createDataFrame([(line,) for line in lines], "value string")


def test_valid_events_are_kept_and_bad_ones_are_rejected_with_their_text(spark):
    good = click(T0, "product_view", product_id=P1, source="search")
    unknown_type = click(T0, "page_view")
    no_id = '{"type": "search", "occurred_at": "2026-11-18T12:00:00Z", "query": "x"}'
    not_json = "this is not json"

    events, rejects = parse_clicks(messages(spark, [good, unknown_type, no_id, not_json]))

    assert events.count() == 1
    assert events.first()["product_id"] == P1
    assert sorted(r["raw"] for r in rejects.collect()) == sorted([unknown_type, no_id, not_json])


def test_only_confirmed_orders_count_as_purchases_and_each_item_keeps_its_product(spark):
    lines = [
        order_confirmed(T0, [(P1, 2), (P2, 1)]),
        order_placed(T0, [(P1, 5)]),
    ]

    purchases = parse_purchases(messages(spark, lines))

    rows = sorted((r["product_id"], r["quantity"]) for r in purchases.collect())
    assert rows == sorted([(P1, 2), (P2, 1)])


def test_product_totals_count_views_carts_and_units_sold_per_five_minute_window(spark):
    clicks_lines = [
        click("2026-11-18T12:01:00Z", "product_view", product_id=P1, source="direct"),
        click("2026-11-18T12:02:00Z", "product_view", product_id=P1, source="search"),
        click("2026-11-18T12:03:00Z", "add_to_cart", product_id=P1, variant_id=str(uuid.uuid4()), quantity=3),
        click("2026-11-18T12:04:00Z", "product_view", product_id=P2, source="category"),
        click("2026-11-18T12:07:00Z", "product_view", product_id=P1, source="direct"),
    ]
    clicks, _ = parse_clicks(messages(spark, clicks_lines))
    purchases = parse_purchases(messages(spark, [order_confirmed("2026-11-18T12:03:30Z", [(P1, 2)])]))

    totals = {
        (r["window_start"].strftime("%H:%M"), str(r["product_id"])): r
        for r in product_totals(activity(clicks, purchases)).collect()
    }

    first = totals[("12:00", P1)]
    assert (first["views"], first["add_to_carts"], first["units_sold"]) == (2, 3, 2)
    assert totals[("12:00", P2)]["views"] == 1
    assert totals[("12:05", P1)]["views"] == 1
    assert totals[("12:05", P1)]["units_sold"] == 0


def test_search_terms_ignore_case_and_spacing(spark):
    lines = [
        click(T0, "search", query="Desk Lamp", result_count=4),
        click(T0, "search", query="  desk lamp ", result_count=4),
        click(T0, "search", query="chair", result_count=9),
    ]
    events, _ = parse_clicks(messages(spark, lines))

    counts = {r["term"]: r["searches"] for r in search_terms(events).collect()}

    assert counts == {"desk lamp": 2, "chair": 1}

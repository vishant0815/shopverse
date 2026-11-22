"""The streaming job end to end, with text files standing in for Kafka and lists for Postgres.

Windows only close when the watermark passes them, which needs later events. So each round
of files below is followed by a later "closing" event, the same way a live stream moves on.
"""

import uuid
from datetime import date

from clickstream.pipeline import Outputs, Sinks, build

from .conftest import click, order_confirmed, product_upserted

P1 = str(uuid.uuid4())
P2 = str(uuid.uuid4())
SELLER = str(uuid.uuid4())
E1 = str(uuid.uuid4())  # a product view that is sent twice


def write_round(directory, name, lines):
    (directory / name).write_text("\n".join(lines) + "\n")


def run_round(queries):
    for query in queries:
        query.processAllAvailable()


def keeping_sink(rows, output_mode):
    """A sink that keeps every row it is given, in order, the way a table would."""
    def start(df, checkpoint):
        def keep(batch, batch_id):
            rows.extend(r.asDict() for r in batch.collect())

        return df.writeStream.outputMode(output_mode).option("checkpointLocation", checkpoint).foreachBatch(keep).start()

    return start


def test_each_event_is_counted_once_and_windows_are_totalled(spark, tmp_path):
    clicks_dir, orders_dir, products_dir = tmp_path / "in" / "clicks", tmp_path / "in" / "orders", tmp_path / "in" / "products"
    for directory in (clicks_dir, orders_dir, products_dir):
        directory.mkdir(parents=True)
    out = Outputs(str(tmp_path / "out"))

    def write_rejects(rejects, checkpoint):
        return (
            rejects.selectExpr("raw AS value")
            .writeStream.format("text")
            .outputMode("append")
            .option("checkpointLocation", checkpoint)
            .option("path", str(tmp_path / "out" / "rejects"))
            .start()
        )

    listings, daily, pairs = [], [], []
    queries = build(
        spark.readStream.text(str(clicks_dir)),
        spark.readStream.text(str(orders_dir)),
        spark.readStream.text(str(products_dir)),
        out,
        Sinks(
            rejects=write_rejects,
            listings=keeping_sink(listings, "append"),
            daily=keeping_sink(daily, "update"),
            pairs=keeping_sink(pairs, "update"),
        ),
    )
    try:
        # Round 1: a view sent twice, a cart, a search (in two spellings), one bad line,
        # a confirmed order for P1, and the catalogue's listing for P1.
        write_round(clicks_dir, "a.txt", [
            click("2026-11-18T12:01:00Z", "product_view", event_id=E1, product_id=P1, source="direct"),
            click("2026-11-18T12:01:00Z", "product_view", event_id=E1, product_id=P1, source="direct"),
            click("2026-11-18T12:02:00Z", "add_to_cart", product_id=P1, variant_id=str(uuid.uuid4()), quantity=2),
            click("2026-11-18T12:03:00Z", "search", query="Desk Lamp", result_count=5),
            click("2026-11-18T12:03:30Z", "search", query=" desk lamp", result_count=5),
            "not an event",
        ])
        write_round(orders_dir, "a.txt", [order_confirmed("2026-11-18T12:03:45Z", [(P1, 1)])])
        write_round(products_dir, "a.txt", [product_upserted(P1, SELLER, "Desk Lamp", revision=2)])
        run_round(queries)

        # Rounds 2 and 3: later events move the watermark past the 12:00 window.
        write_round(clicks_dir, "b.txt", [click("2026-11-18T13:00:00Z", "product_view", product_id=P2, source="direct")])
        run_round(queries)
        write_round(clicks_dir, "c.txt", [click("2026-11-18T13:10:00Z", "product_view", product_id=P2, source="direct")])
        run_round(queries)
    finally:
        for query in queries:
            query.stop()

    raw = spark.read.parquet(out.path("raw_events"))
    assert raw.where(raw.event_id == E1).count() == 1

    totals = {
        (r["window_start"].strftime("%H:%M"), str(r["product_id"])): r
        for r in spark.read.parquet(out.path("product_totals")).collect()
    }
    first = totals[("12:00", P1)]
    assert (first["views"], first["add_to_carts"], first["units_sold"]) == (1, 2, 1)

    terms = {r["term"]: r["searches"] for r in spark.read.parquet(out.path("search_terms")).collect()}
    assert terms == {"desk lamp": 2}

    rejected = spark.read.text(str(tmp_path / "out" / "rejects")).collect()
    assert [r["value"] for r in rejected] == ["not an event"]

    # The listing carries the seller and name. The sink keeps every row it is given; the table
    # itself keeps the newest revision (see the Postgres tests).
    assert [(str(r["product_id"]), str(r["seller_id"]), r["name"]) for r in listings] == [(P1, SELLER, "Desk Lamp")]

    # The daily sink receives every change. The last row for each product and day is the total.
    latest = {}
    for row in daily:
        latest[(str(row["product_id"]), row["day"])] = row
    day_p1 = latest[(P1, date(2026, 11, 18))]
    assert (day_p1["views"], day_p1["add_to_carts"], day_p1["units_sold"]) == (1, 2, 1)

    # That order had one product, so it pairs with nothing.
    assert pairs == []


def test_an_order_with_several_items_counts_every_item_and_pairs_its_products(spark, tmp_path):
    """Each item of a confirmed order is a sale, and each two products in the order are bought together once."""
    clicks_dir, orders_dir, products_dir = tmp_path / "clicks", tmp_path / "orders", tmp_path / "products"
    for directory in (clicks_dir, orders_dir, products_dir):
        directory.mkdir()
    daily, pairs = [], []

    def write_rejects(rejects, checkpoint):
        return (
            rejects.selectExpr("raw AS value").writeStream.format("text").outputMode("append")
            .option("checkpointLocation", checkpoint).option("path", str(tmp_path / "rejects")).start()
        )

    queries = build(
        spark.readStream.text(str(clicks_dir)),
        spark.readStream.text(str(orders_dir)),
        spark.readStream.text(str(products_dir)),
        Outputs(str(tmp_path / "out")),
        Sinks(
            rejects=write_rejects,
            listings=keeping_sink([], "append"),
            daily=keeping_sink(daily, "update"),
            pairs=keeping_sink(pairs, "update"),
        ),
    )
    try:
        write_round(orders_dir, "a.txt", [order_confirmed("2026-11-18T12:03:45Z", [(P1, 1), (P2, 2)])])
        run_round(queries)
        write_round(clicks_dir, "a.txt", [click("2026-11-18T13:00:00Z", "product_view", product_id=P2, source="direct")])
        run_round(queries)
    finally:
        for query in queries:
            query.stop()

    latest = {}
    for row in daily:
        latest[(str(row["product_id"]), row["day"])] = row
    assert latest[(P1, date(2026, 11, 18))]["units_sold"] == 1
    assert latest[(P2, date(2026, 11, 18))]["units_sold"] == 2

    counts = {}
    for row in pairs:
        counts[(str(row["product_id"]), str(row["related_id"]))] = row["shared_orders"]
    assert counts == {(P1, P2): 1, (P2, P1): 1}

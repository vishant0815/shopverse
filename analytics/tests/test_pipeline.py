"""The streaming job end to end, with text files standing in for Kafka.

Windows only close when the watermark passes them, which needs later events. So each round
of files below is followed by a later "closing" event, the same way a live stream moves on.
"""

import uuid

from clickstream.pipeline import Outputs, build

from .conftest import click, order_confirmed

P1 = str(uuid.uuid4())
P2 = str(uuid.uuid4())
E1 = str(uuid.uuid4())  # a product view that is sent twice


def write_round(directory, name, lines):
    (directory / name).write_text("\n".join(lines) + "\n")


def run_round(queries):
    for query in queries:
        query.processAllAvailable()


def test_each_event_is_counted_once_and_windows_are_totalled(spark, tmp_path):
    clicks_dir, orders_dir = tmp_path / "in" / "clicks", tmp_path / "in" / "orders"
    clicks_dir.mkdir(parents=True)
    orders_dir.mkdir(parents=True)
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

    queries = build(
        spark.readStream.text(str(clicks_dir)),
        spark.readStream.text(str(orders_dir)),
        out,
        write_rejects,
    )
    try:
        # Round 1: a view sent twice, a cart, a search (in two spellings), one bad line,
        # and a confirmed order for P1.
        write_round(clicks_dir, "a.txt", [
            click("2026-11-18T12:01:00Z", "product_view", event_id=E1, product_id=P1, source="direct"),
            click("2026-11-18T12:01:00Z", "product_view", event_id=E1, product_id=P1, source="direct"),
            click("2026-11-18T12:02:00Z", "add_to_cart", product_id=P1, variant_id=str(uuid.uuid4()), quantity=2),
            click("2026-11-18T12:03:00Z", "search", query="Desk Lamp", result_count=5),
            click("2026-11-18T12:03:30Z", "search", query=" desk lamp", result_count=5),
            "not an event",
        ])
        write_round(orders_dir, "a.txt", [order_confirmed("2026-11-18T12:03:45Z", [(P1, 1)])])
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

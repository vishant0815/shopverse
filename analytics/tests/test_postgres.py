"""The Postgres writes, against a real database.

Set ANALYTICS_TEST_DATABASE_URL to a database that can be emptied: its analytics tables are
cleared before each test. Without it these tests are skipped.
"""

import os
import uuid
from datetime import date
from pathlib import Path

import psycopg
import pytest

from clickstream.pipeline import Outputs, Sinks, build
from clickstream.postgres import (
    DAILY_COLUMNS,
    DAILY_UPSERT,
    LISTING_COLUMNS,
    LISTING_UPSERT,
    apply_schema,
    daily_sink,
    listing_sink,
    write_rows,
)

from .conftest import click, order_confirmed, product_upserted

DATABASE_URL = os.environ.get("ANALYTICS_TEST_DATABASE_URL")
SCHEMA = Path(__file__).resolve().parents[2] / "infra" / "postgres" / "analytics" / "schema.sql"

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="set ANALYTICS_TEST_DATABASE_URL to run the Postgres tests",
)


@pytest.fixture
def db():
    apply_schema(DATABASE_URL, str(SCHEMA))
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE product_listings, product_daily")
    return DATABASE_URL


def listing(product_id, seller_id, name, revision):
    return {
        "product_id": product_id, "seller_id": seller_id, "name": name,
        "slug": name.lower().replace(" ", "-"), "image_url": "", "revision": revision,
    }


def daily(product_id, views, carts, sold, day=date(2026, 11, 18)):
    return {
        "product_id": product_id, "day": day, "views": views,
        "add_to_carts": carts, "units_sold": sold,
    }


def fetch(url, sql):
    with psycopg.connect(url) as conn:
        return conn.execute(sql).fetchall()


def test_applying_the_schema_twice_is_safe(db):
    apply_schema(db, str(SCHEMA))
    apply_schema(db, str(SCHEMA))


def test_a_newer_listing_replaces_an_older_one_and_a_late_older_one_is_ignored(db):
    product, seller = str(uuid.uuid4()), str(uuid.uuid4())

    write_rows(db, LISTING_UPSERT, LISTING_COLUMNS, [listing(product, seller, "Desk Lamp", 2)])
    write_rows(db, LISTING_UPSERT, LISTING_COLUMNS, [listing(product, seller, "Old Lamp", 1)])

    assert fetch(db, "SELECT name, revision FROM product_listings") == [("Desk Lamp", 2)]


def test_daily_totals_are_replaced_so_running_a_batch_again_changes_nothing(db):
    product = str(uuid.uuid4())

    write_rows(db, DAILY_UPSERT, DAILY_COLUMNS, [daily(product, 1, 2, 1)])
    write_rows(db, DAILY_UPSERT, DAILY_COLUMNS, [daily(product, 5, 2, 1)])
    write_rows(db, DAILY_UPSERT, DAILY_COLUMNS, [daily(product, 5, 2, 1)])

    assert fetch(db, "SELECT views, add_to_carts, units_sold FROM product_daily") == [(5, 2, 1)]


def test_a_partition_with_no_rows_writes_nothing(db):
    write_rows(db, DAILY_UPSERT, DAILY_COLUMNS, [])

    assert fetch(db, "SELECT count(*) FROM product_daily") == [(0,)]


def test_the_spark_job_writes_listings_and_daily_totals_to_postgres(spark, tmp_path, db):
    """The real sinks, run by Spark: rows reach the tables through the executors."""
    clicks_dir, orders_dir, products_dir = tmp_path / "clicks", tmp_path / "orders", tmp_path / "products"
    for directory in (clicks_dir, orders_dir, products_dir):
        directory.mkdir()
    product, seller = str(uuid.uuid4()), str(uuid.uuid4())

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
        Sinks(rejects=write_rejects, listings=listing_sink(db), daily=daily_sink(db)),
    )
    try:
        (products_dir / "a.txt").write_text(product_upserted(product, seller, "Desk Lamp", revision=2) + "\n")
        (clicks_dir / "a.txt").write_text("\n".join([
            click("2026-11-18T12:01:00Z", "product_view", product_id=product, source="direct"),
            click("2026-11-18T12:02:00Z", "add_to_cart", product_id=product, variant_id=str(uuid.uuid4()), quantity=2),
        ]) + "\n")
        (orders_dir / "a.txt").write_text(order_confirmed("2026-11-18T12:03:00Z", [(product, 1)]) + "\n")
        for query in queries:
            query.processAllAvailable()
        # A later event moves the watermark past the day's start so the day stays up to date.
        (clicks_dir / "b.txt").write_text(click("2026-11-19T12:00:00Z", "product_view", product_id=product) + "\n")
        for query in queries:
            query.processAllAvailable()
    finally:
        for query in queries:
            query.stop()

    assert fetch(db, "SELECT seller_id::text, name FROM product_listings") == [(seller, "Desk Lamp")]
    assert fetch(db, "SELECT views, add_to_carts, units_sold FROM product_daily WHERE day = '2026-11-18'") == [(1, 2, 1)]

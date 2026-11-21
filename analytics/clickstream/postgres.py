"""Writes the analytics tables to Postgres, where the analytics API reads them.

Every write is an upsert keyed by the table's primary key, so a micro-batch that runs again after
a restart leaves the same numbers behind. Each partition of a batch opens one connection.
"""

from functools import partial

import psycopg
from pyspark.sql import DataFrame

from .pipeline import SinkStarter

# A listing is replaced only by the same or a newer revision, so a late, older message never
# undoes a newer one.
LISTING_COLUMNS = ["product_id", "seller_id", "name", "slug", "image_url", "revision"]
LISTING_UPSERT = """
    INSERT INTO product_listings (product_id, seller_id, name, slug, image_url, revision)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (product_id) DO UPDATE SET
        seller_id = EXCLUDED.seller_id,
        name = EXCLUDED.name,
        slug = EXCLUDED.slug,
        image_url = EXCLUDED.image_url,
        revision = EXCLUDED.revision,
        updated_at = now()
    WHERE product_listings.revision <= EXCLUDED.revision
"""

# Spark sends a day's full totals each time they change, so the row is replaced, not added to.
DAILY_COLUMNS = ["product_id", "day", "views", "add_to_carts", "units_sold"]
DAILY_UPSERT = """
    INSERT INTO product_daily (product_id, day, views, add_to_carts, units_sold)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (product_id, day) DO UPDATE SET
        views = EXCLUDED.views,
        add_to_carts = EXCLUDED.add_to_carts,
        units_sold = EXCLUDED.units_sold
"""


def apply_schema(database_url: str, path: str) -> None:
    """Creates the tables from the schema file. Every statement uses IF NOT EXISTS, so this is safe on each start."""
    with open(path, encoding="utf-8") as file:
        sql = file.read()
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(sql)


def write_rows(database_url: str, sql: str, columns: list[str], rows) -> None:
    """Runs the upsert for every row of one partition in a single transaction."""
    batch = [tuple(row[column] for column in columns) for row in rows]
    if not batch:
        return
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cursor:
            cursor.executemany(sql, batch)


def _sink(database_url: str, sql: str, columns: list[str], output_mode: str) -> SinkStarter:
    def start(df: DataFrame, checkpoint: str):
        def write_batch(batch: DataFrame, batch_id: int) -> None:
            batch.select(*columns).foreachPartition(partial(write_rows, database_url, sql, columns))

        return df.writeStream.outputMode(output_mode).option("checkpointLocation", checkpoint).foreachBatch(
            write_batch
        ).start()

    return start


def listing_sink(database_url: str) -> SinkStarter:
    """product_listings. Appends new rows as the catalogue announces them."""
    return _sink(database_url, LISTING_UPSERT, LISTING_COLUMNS, "append")


def daily_sink(database_url: str) -> SinkStarter:
    """product_daily. Update mode sends only the days whose totals changed."""
    return _sink(database_url, DAILY_UPSERT, DAILY_COLUMNS, "update")

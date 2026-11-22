"""Turns raw Kafka messages into the tables the rest of the platform reads.

These are plain DataFrame functions with no Kafka in them, so they run the same way on a
batch of test rows as on the live stream. pipeline.py wires them into streaming queries.

Tables that come out:
- raw events: every accepted storefront event, as received (Parquet)
- product totals: views, add-to-carts and units sold per product in five-minute windows (Parquet)
- search terms: how often each search term was run in each window (Parquet)
- product listings: which seller owns each product, from the catalogue (Postgres)
- product daily: views, add-to-carts and units sold per product per UTC day (Postgres)
- product pairs: how many confirmed orders each two products shared, in both directions (Postgres)
"""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import ArrayType, IntegerType, StringType, StructField, StructType

WINDOW = "5 minutes"
WATERMARK = "10 minutes"
CLICK_TYPES = ("product_view", "search", "add_to_cart")

# Every field any storefront event can carry. Fields an event doesn't use are null.
CLICK_SCHEMA = StructType([
    StructField("event_id", StringType()),
    StructField("type", StringType()),
    StructField("occurred_at", StringType()),
    StructField("received_at", StringType()),
    StructField("session_id", StringType()),
    StructField("user_id", StringType()),
    StructField("product_id", StringType()),
    StructField("variant_id", StringType()),
    StructField("source", StringType()),
    StructField("query", StringType()),
    StructField("result_count", IntegerType()),
    StructField("quantity", IntegerType()),
])

# The envelope every service puts around its messages (see docs/events.md). Only the parts
# the job reads are named; from_json ignores the rest.
ENVELOPE_SCHEMA = StructType([
    StructField("id", StringType()),
    StructField("type", StringType()),
    StructField("occurred_at", StringType()),
    StructField("data", StructType([
        StructField("items", ArrayType(StructType([
            StructField("product_id", StringType()),
            StructField("quantity", IntegerType()),
        ]))),
    ])),
])


# The parts of a ProductUpserted message the listings table keeps (the product document in
# services/products/catalog/events.py).
PRODUCT_ENVELOPE_SCHEMA = StructType([
    StructField("type", StringType()),
    StructField("data", StructType([
        StructField("product_id", StringType()),
        StructField("seller_id", StringType()),
        StructField("revision", IntegerType()),
        StructField("name", StringType()),
        StructField("slug", StringType()),
        StructField("image_url", StringType()),
    ])),
])


def parse_listings(raw: DataFrame) -> DataFrame:
    """One row per product from ProductUpserted messages: its seller, name, slug and revision.

    Other catalogue messages are skipped. Nothing is written for a message missing a field the
    table needs; the catalogue sends every field, so that only happens for a broken message.
    """
    parsed = raw.select(F.from_json(F.col("value").cast("string"), PRODUCT_ENVELOPE_SCHEMA).alias("m"))
    upserted = parsed.where(F.col("m.type") == "ProductUpserted").select("m.data.*")
    complete = (
        F.col("product_id").isNotNull()
        & F.col("seller_id").isNotNull()
        & F.col("revision").isNotNull()
        & F.col("name").isNotNull()
        & F.col("slug").isNotNull()
    )
    return upserted.where(complete).select(
        "product_id", "seller_id", "name", "slug", F.coalesce("image_url", F.lit("")).alias("image_url"), "revision",
    )


def parse_clicks(raw: DataFrame) -> tuple[DataFrame, DataFrame]:
    """Split raw clickstream messages (a JSON string in `value`) into valid events and rejects.

    A message is valid when it has an id, a known type and a time. Anything else goes to
    rejects, with its original text, so nothing is silently dropped.
    """
    parsed = raw.select(
        F.col("value").cast("string").alias("raw"),
        F.from_json(F.col("value").cast("string"), CLICK_SCHEMA).alias("e"),
    )
    valid = F.coalesce(
        F.col("e.event_id").isNotNull() & F.col("e.type").isin(*CLICK_TYPES) & F.col("e.occurred_at").isNotNull(),
        F.lit(False),
    )
    events = (
        parsed.where(valid)
        .select("e.*")
        .withColumn("occurred_at", F.to_timestamp("occurred_at"))
        .withColumn("received_at", F.to_timestamp("received_at"))
    )
    rejects = parsed.where(~valid).select("raw")
    return events, rejects


def parse_orders(raw: DataFrame) -> DataFrame:
    """One row per confirmed order (a payment has gone through), with its item lines.

    The order events are shared with other consumers, so everything except OrderConfirmed is
    skipped here.
    """
    envelopes = raw.select(F.from_json(F.col("value").cast("string"), ENVELOPE_SCHEMA).alias("m"))
    confirmed = envelopes.where(F.col("m.type") == "OrderConfirmed")
    return confirmed.select(
        F.col("m.id").alias("event_id"),
        F.to_timestamp("m.occurred_at").alias("occurred_at"),
        F.col("m.data.items").alias("items"),
    )


def purchase_lines(orders: DataFrame) -> DataFrame:
    """One row per item of each order. Every item keeps the order's event id."""
    return orders.select("event_id", "occurred_at", F.explode("items").alias("item")).select(
        "event_id", "occurred_at", F.col("item.product_id"), F.col("item.quantity"),
    )


def parse_purchases(raw: DataFrame) -> DataFrame:
    """One row per item of each confirmed order. See parse_orders and purchase_lines."""
    return purchase_lines(parse_orders(raw))


# For one order's sorted, distinct product ids (the column `ids`), every pair of them with the
# first before the second. Each pair becomes one struct; flatten joins them into one array.
PAIRS_EXPR = (
    "flatten(transform(ids, (a, i) -> "
    "transform(slice(ids, i + 2, size(ids)), b -> struct(a AS product_id, b AS related_id))))"
)


def co_purchases(orders: DataFrame) -> DataFrame:
    """Each two products in an order, once in each direction as (product_id, related_id).

    An order with one product, or none, makes no pairs. A product listed twice in one order counts once.
    """
    with_ids = orders.select(
        "event_id",
        F.array_sort(F.array_distinct(F.transform("items", lambda item: item.product_id))).alias("ids"),
    )
    pairs = with_ids.select("event_id", F.explode(F.expr(PAIRS_EXPR)).alias("pair")).select(
        "event_id", F.col("pair.product_id"), F.col("pair.related_id"),
    )
    reverse = pairs.select(
        "event_id", F.col("related_id").alias("product_id"), F.col("product_id").alias("related_id"),
    )
    return pairs.unionByName(reverse)


def pair_counts(orders: DataFrame) -> DataFrame:
    """How many confirmed orders each product shared with each other product, in both directions.

    These are running totals over the whole stream, so the table is rewritten as they change.
    """
    return co_purchases(orders).groupBy("product_id", "related_id").agg(F.count("*").alias("shared_orders"))


def activity(clicks: DataFrame, purchases: DataFrame) -> DataFrame:
    """Views, add-to-carts and purchases as one list, so one aggregation can total them."""
    views = clicks.where(F.col("type") == "product_view").select(
        "event_id", "occurred_at", "product_id", F.lit("view").alias("kind"), F.lit(1).alias("units"),
    )
    carts = clicks.where(F.col("type") == "add_to_cart").select(
        "event_id", "occurred_at", "product_id", F.lit("cart").alias("kind"), F.col("quantity").alias("units"),
    )
    buys = purchases.select(
        "event_id", "occurred_at", "product_id", F.lit("purchase").alias("kind"), F.col("quantity").alias("units"),
    )
    return views.unionByName(carts).unionByName(buys)


def _totals_by_window(activity_df: DataFrame, duration: str):
    """Views, add-to-carts and units sold per product in windows of the given length."""
    return (
        activity_df.groupBy(F.window("occurred_at", duration).alias("w"), "product_id")
        .agg(
            F.sum(F.when(F.col("kind") == "view", F.col("units")).otherwise(0)).alias("views"),
            F.sum(F.when(F.col("kind") == "cart", F.col("units")).otherwise(0)).alias("add_to_carts"),
            F.sum(F.when(F.col("kind") == "purchase", F.col("units")).otherwise(0)).alias("units_sold"),
        )
    )


def product_totals(activity_df: DataFrame) -> DataFrame:
    """Per product and five-minute window: views, add-to-carts and units sold."""
    return _totals_by_window(activity_df, WINDOW).select(
        F.col("w.start").alias("window_start"),
        F.col("w.end").alias("window_end"),
        "product_id", "views", "add_to_carts", "units_sold",
    )


def product_daily(activity_df: DataFrame) -> DataFrame:
    """Per product and UTC day: views, add-to-carts and units sold. The seller analytics read these.

    Windows start at midnight UTC because the session time zone is UTC (see job.py).
    """
    return _totals_by_window(activity_df, "1 day").select(
        F.to_date(F.col("w.start")).alias("day"),
        "product_id", "views", "add_to_carts", "units_sold",
    )


def search_terms(clicks: DataFrame) -> DataFrame:
    """How often each search term was run in each five-minute window. Case and spacing are ignored."""
    return (
        clicks.where(F.col("type") == "search")
        .select("occurred_at", F.lower(F.trim(F.col("query"))).alias("term"))
        .groupBy(F.window("occurred_at", WINDOW).alias("w"), "term")
        .agg(F.count("*").alias("searches"))
        .select(F.col("w.start").alias("window_start"), F.col("w.end").alias("window_end"), "term", "searches")
    )

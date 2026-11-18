"""Turns raw Kafka messages into the tables the rest of the platform reads.

These are plain DataFrame functions with no Kafka in them, so they run the same way on a
batch of test rows as on the live stream. pipeline.py wires them into streaming queries.

Three tables come out:
- raw events: every accepted storefront event, as received
- product totals: views, add-to-carts and units sold per product in five-minute windows
- search terms: how often each search term was run in each window
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


def parse_purchases(raw: DataFrame) -> DataFrame:
    """One row per item of each confirmed order (a payment has gone through).

    The order events are shared with other consumers, so everything except OrderConfirmed is
    skipped here.
    """
    envelopes = raw.select(F.from_json(F.col("value").cast("string"), ENVELOPE_SCHEMA).alias("m"))
    confirmed = envelopes.where(F.col("m.type") == "OrderConfirmed")
    return confirmed.select(
        F.col("m.id").alias("event_id"),
        F.to_timestamp("m.occurred_at").alias("occurred_at"),
        F.explode("m.data.items").alias("item"),
    ).select("event_id", "occurred_at", F.col("item.product_id"), F.col("item.quantity"))


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


def product_totals(activity_df: DataFrame) -> DataFrame:
    """Per product and five-minute window: views, add-to-carts and units sold."""
    return (
        activity_df.groupBy(F.window("occurred_at", WINDOW).alias("w"), "product_id")
        .agg(
            F.sum(F.when(F.col("kind") == "view", F.col("units")).otherwise(0)).alias("views"),
            F.sum(F.when(F.col("kind") == "cart", F.col("units")).otherwise(0)).alias("add_to_carts"),
            F.sum(F.when(F.col("kind") == "purchase", F.col("units")).otherwise(0)).alias("units_sold"),
        )
        .select(
            F.col("w.start").alias("window_start"),
            F.col("w.end").alias("window_end"),
            "product_id", "views", "add_to_carts", "units_sold",
        )
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

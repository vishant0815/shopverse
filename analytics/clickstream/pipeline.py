"""The streaming queries for the analytics job.

build() takes the raw streams and returns the running queries. job.py feeds it Kafka streams and
real sinks; the tests feed it text files and in-memory sinks, so watermarks, de-duplication and
windows are tested without a broker or a database.

Repeats are dropped by event id within the watermark. A message that is sent twice, such as a
batch the collector asked the browser to resend, is counted once.
"""

from collections.abc import Callable
from dataclasses import dataclass

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.streaming import StreamingQuery

from .transforms import (
    WATERMARK,
    activity,
    parse_clicks,
    parse_listings,
    parse_purchases,
    product_daily,
    product_totals,
    search_terms,
)


@dataclass(frozen=True)
class Outputs:
    """Where the Parquet tables and their checkpoints live (the analytics volume)."""

    root: str

    def path(self, name: str) -> str:
        return f"{self.root}/{name}"

    def checkpoint(self, name: str) -> str:
        return f"{self.root}/_checkpoints/{name}"


# Starts a query that writes one stream somewhere (Kafka, Postgres, or a test sink).
SinkStarter = Callable[[DataFrame, str], StreamingQuery]


@dataclass(frozen=True)
class Sinks:
    rejects: SinkStarter  # messages that couldn't be read, kept with their text
    listings: SinkStarter  # product_listings: which seller owns each product
    daily: SinkStarter  # product_daily: totals per product per day, rewritten as they change


def build(
    clicks_raw: DataFrame,
    orders_raw: DataFrame,
    products_raw: DataFrame,
    out: Outputs,
    sinks: Sinks,
) -> list[StreamingQuery]:
    # With several watermarked inputs Spark's default ("min") waits for the slowest one. The
    # orders stream can go quiet for hours, which would hold every window open. "max" lets the
    # windows close as the busiest stream moves on; a purchase that arrives more than the
    # watermark late is then dropped from the totals.
    clicks_raw.sparkSession.conf.set("spark.sql.streaming.multipleWatermarkPolicy", "max")

    events, rejects = parse_clicks(clicks_raw)
    events = events.withWatermark("occurred_at", WATERMARK).dropDuplicatesWithinWatermark(["event_id"])

    purchases = (
        parse_purchases(orders_raw)
        .withWatermark("occurred_at", WATERMARK)
        .dropDuplicatesWithinWatermark(["event_id"])
    )
    totals_source = activity(events, purchases)

    raw_events = events.withColumn("date", F.to_date("occurred_at")).withColumn("hour", F.hour("occurred_at"))

    return [
        _parquet(raw_events, out, "raw_events", partition_by=["date", "hour"]),
        _parquet(product_totals(totals_source), out, "product_totals"),
        _parquet(search_terms(events), out, "search_terms"),
        sinks.rejects(rejects, out.checkpoint("rejects")),
        sinks.listings(parse_listings(products_raw), out.checkpoint("listings")),
        sinks.daily(product_daily(totals_source), out.checkpoint("daily")),
    ]


def _parquet(df: DataFrame, out: Outputs, name: str, partition_by: list[str] | None = None) -> StreamingQuery:
    writer = (
        df.writeStream.format("parquet")
        .outputMode("append")
        .option("path", out.path(name))
        .option("checkpointLocation", out.checkpoint(name))
    )
    if partition_by:
        writer = writer.partitionBy(*partition_by)
    return writer.queryName(name).start()

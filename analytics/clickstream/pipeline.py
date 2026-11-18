"""The streaming queries for the clickstream job.

build() takes the raw streams and returns the running queries. job.py feeds it Kafka streams;
the tests feed it text files, so watermarks, de-duplication and windows are tested without a
broker.

Repeats are dropped by event id within the watermark. A message that is sent twice, such as a
batch the collector asked the browser to resend, is counted once.
"""

from collections.abc import Callable
from dataclasses import dataclass

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.streaming import StreamingQuery

from .transforms import WATERMARK, activity, parse_clicks, parse_purchases, product_totals, search_terms


@dataclass(frozen=True)
class Outputs:
    """Where the Parquet tables and their checkpoints live (the analytics volume)."""

    root: str

    def path(self, name: str) -> str:
        return f"{self.root}/{name}"

    def checkpoint(self, name: str) -> str:
        return f"{self.root}/_checkpoints/{name}"


# Starts a query that writes rejected messages somewhere they can be inspected.
RejectWriter = Callable[[DataFrame, str], StreamingQuery]


def build(
    clicks_raw: DataFrame,
    orders_raw: DataFrame,
    out: Outputs,
    write_rejects: RejectWriter,
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

    raw_events = events.withColumn("date", F.to_date("occurred_at")).withColumn("hour", F.hour("occurred_at"))

    return [
        _parquet(raw_events, out, "raw_events", partition_by=["date", "hour"]),
        _parquet(product_totals(activity(events, purchases)), out, "product_totals"),
        _parquet(search_terms(events), out, "search_terms"),
        write_rejects(rejects, out.checkpoint("rejects")),
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

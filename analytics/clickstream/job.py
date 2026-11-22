"""Runs the analytics job: reads Kafka, writes Parquet to the analytics volume and writes the seller
analytics tables to Postgres.

Submitted with spark-submit (see the Dockerfile). Configuration comes from environment variables:
- KAFKA_BOOTSTRAP_SERVERS: where the brokers are, e.g. kafka:9092
- ANALYTICS_OUTPUT_DIR: where the Parquet tables and checkpoints go (default /data/analytics)
- ANALYTICS_DATABASE_URL: the analytics database, e.g. postgresql://user:pass@postgres:5432/analytics
- ANALYTICS_SCHEMA_PATH: the schema file applied on start (default /schema/schema.sql)
"""

import os

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.streaming import StreamingQuery

from clickstream.pipeline import Outputs, Sinks, build
from clickstream.postgres import apply_schema, daily_sink, listing_sink, pairs_sink

CLICKSTREAM_TOPIC = "clickstream.events"
ORDERS_TOPIC = "orders.events"
PRODUCTS_TOPIC = "catalog.products"
REJECTS_TOPIC = "clickstream.events.dlq"


def kafka_stream(spark: SparkSession, bootstrap: str, topic: str) -> DataFrame:
    return (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", bootstrap)
        .option("subscribe", topic)
        .option("startingOffsets", "earliest")
        .load()
    )


def kafka_rejects(bootstrap: str):
    def write(rejects: DataFrame, checkpoint: str) -> StreamingQuery:
        return (
            rejects.selectExpr("raw AS value")
            .writeStream.format("kafka")
            .option("kafka.bootstrap.servers", bootstrap)
            .option("topic", REJECTS_TOPIC)
            .option("checkpointLocation", checkpoint)
            .start()
        )

    return write


def main() -> None:
    bootstrap = os.environ["KAFKA_BOOTSTRAP_SERVERS"]
    root = os.environ.get("ANALYTICS_OUTPUT_DIR", "/data/analytics")
    database_url = os.environ["ANALYTICS_DATABASE_URL"]
    schema_path = os.environ.get("ANALYTICS_SCHEMA_PATH", "/schema/schema.sql")

    # The tables must exist before any query writes to them.
    apply_schema(database_url, schema_path)

    # Windows start at midnight UTC, so daily totals are per UTC day.
    spark = (
        SparkSession.builder.appName("shopverse-analytics")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    build(
        kafka_stream(spark, bootstrap, CLICKSTREAM_TOPIC),
        kafka_stream(spark, bootstrap, ORDERS_TOPIC),
        kafka_stream(spark, bootstrap, PRODUCTS_TOPIC),
        Outputs(root),
        Sinks(
            rejects=kafka_rejects(bootstrap),
            listings=listing_sink(database_url),
            daily=daily_sink(database_url),
            pairs=pairs_sink(database_url),
        ),
    )
    spark.streams.awaitAnyTermination()


if __name__ == "__main__":
    main()

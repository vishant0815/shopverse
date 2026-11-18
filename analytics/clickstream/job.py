"""Runs the clickstream job: reads Kafka and writes Parquet to the analytics volume.

Submitted with spark-submit (see the Dockerfile). Configuration comes from environment variables:
- KAFKA_BOOTSTRAP_SERVERS: where the brokers are, e.g. kafka:9092
- ANALYTICS_OUTPUT_DIR: where the tables and checkpoints go (default /data/analytics)
"""

import os

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.streaming import StreamingQuery

from clickstream.pipeline import Outputs, build

CLICKSTREAM_TOPIC = "clickstream.events"
ORDERS_TOPIC = "orders.events"
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

    spark = SparkSession.builder.appName("shopverse-clickstream").getOrCreate()
    spark.sparkContext.setLogLevel("WARN")

    build(
        kafka_stream(spark, bootstrap, CLICKSTREAM_TOPIC),
        kafka_stream(spark, bootstrap, ORDERS_TOPIC),
        Outputs(root),
        kafka_rejects(bootstrap),
    )
    spark.streams.awaitAnyTermination()


if __name__ == "__main__":
    main()

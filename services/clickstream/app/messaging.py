"""Kafka producer for clickstream events.

Accepting an event means it is queued for Kafka, not that Kafka has stored it. Analytics can
tolerate losing a few events while a broker is down, so requests don't wait for delivery.
Delivery failures are logged by the callback. Every event carries an event_id, so a batch
that is sent again is counted once by Spark.
"""

import json
import logging

from confluent_kafka import KafkaException, Producer
from confluent_kafka.admin import AdminClient, NewTopic

log = logging.getLogger("clickstream")


class QueueFull(Exception):
    """The producer's local queue is full, so the event was not queued."""


class Publisher:
    def __init__(self, bootstrap: str, topic: str, producer: Producer | None = None):
        self.topic = topic
        self._producer = producer or Producer(
            {"bootstrap.servers": bootstrap, "acks": "all", "enable.idempotence": True, "linger.ms": 20}
        )

    def send(self, key: str, payload: dict) -> None:
        try:
            self._producer.produce(
                self.topic,
                key=key.encode(),
                value=json.dumps(payload).encode(),
                on_delivery=_log_failure,
            )
        except BufferError as exc:
            raise QueueFull() from exc
        self._producer.poll(0)

    def close(self) -> None:
        self._producer.flush(10)


def _log_failure(err, _message) -> None:
    if err is not None:
        log.error("clickstream delivery failed: %s", err)


def ensure_topics(bootstrap: str, topic: str, partitions: int = 3) -> None:
    """Create the topic and its dead-letter twin if they don't exist yet."""
    admin = AdminClient({"bootstrap.servers": bootstrap})
    wanted = [topic, f"{topic}.dlq"]
    existing = set(admin.list_topics(timeout=10).topics)
    missing = [NewTopic(t, num_partitions=partitions, replication_factor=1) for t in wanted if t not in existing]
    for future in admin.create_topics(missing).values() if missing else []:
        try:
            future.result()
        except KafkaException as exc:
            if "TOPIC_ALREADY_EXISTS" not in str(exc):
                raise

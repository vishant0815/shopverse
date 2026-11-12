"""Reads catalogue messages from Kafka and applies them to the search index.

The same rules as the other services: an offset is committed only once its message has been
applied. Elasticsearch being unreachable is waited out without counting as an attempt. Any other
failure gets three attempts, then the message goes to <topic>.dlq with the error and the original
offset as headers. The search service publishes nothing, so there is no outbox here.
"""

import logging
import time

from confluent_kafka import Consumer, KafkaException, Producer
from confluent_kafka.admin import AdminClient, NewTopic
from elastic_transport import ConnectionError as TransportConnectionError
from elastic_transport import ConnectionTimeout
from elasticsearch import ApiError, Elasticsearch

from .index import ensure_index
from .indexer import PoisonMessage, process

log = logging.getLogger("search.consumer")

MAX_ATTEMPTS = 3
TRANSIENT_STATUSES = {429, 503, 504}


def is_index_missing(exc: Exception) -> bool:
    return isinstance(exc, ApiError) and exc.status_code == 404 and "index_not_found_exception" in str(exc)


def is_transient(exc: Exception) -> bool:
    """Elasticsearch is down, restarting or overloaded, or the index is missing: wait it out rather
    than count it. Only a message that is wrong in itself should use up its attempts."""
    if isinstance(exc, (TransportConnectionError, ConnectionTimeout)):
        return True
    if isinstance(exc, ApiError):
        return exc.status_code in TRANSIENT_STATUSES or is_index_missing(exc)
    return False


def ensure_topics(bootstrap: str, topics: list[str], partitions: int = 3) -> None:
    """Create the topics, and their dead-letter twins, if they don't exist yet."""
    admin = AdminClient({"bootstrap.servers": bootstrap})
    wanted = topics + [f"{topic}.dlq" for topic in topics]
    existing = set(admin.list_topics(timeout=10).topics)
    missing = [NewTopic(t, num_partitions=partitions, replication_factor=1) for t in wanted if t not in existing]
    if not missing:
        return
    for future in admin.create_topics(missing).values():
        try:
            future.result()
        except KafkaException as exc:
            if "TOPIC_ALREADY_EXISTS" not in str(exc):
                raise


class SearchConsumer:
    def __init__(self, *, es: Elasticsearch, index: str, bootstrap: str, group: str, topics: list[str]):
        self.es, self.index = es, index
        self.bootstrap, self.group, self.topics = bootstrap, group, topics
        self.consumer = None
        self.producer = None
        self.stopping = False
        self.handled = 0  # messages whose offset has been committed (applied, or dead-lettered)

    def start(self) -> None:
        ensure_topics(self.bootstrap, self.topics)
        self.producer = Producer({
            "bootstrap.servers": self.bootstrap,
            "enable.idempotence": True,
            "acks": "all",
        })
        self.consumer = Consumer({
            "bootstrap.servers": self.bootstrap,
            "group.id": self.group,
            "enable.auto.commit": False,  # committed by hand, after the index write
            "auto.offset.reset": "earliest",
        })
        self.consumer.subscribe(self.topics)

    def stop(self) -> None:
        self.stopping = True

    def run(self) -> None:
        self.start()
        log.info("search consumer %s started on %s", self.group, ", ".join(self.topics))
        try:
            while not self.stopping:
                self.tick()
        finally:
            self.consumer.close()
            self.producer.flush(10)

    def tick(self, poll_timeout: float = 0.5) -> None:
        message = self.consumer.poll(poll_timeout)
        if message is None:
            return
        if message.error():
            log.warning("kafka: %s", message.error())
            return
        self.handle(message)

    def handle(self, message) -> None:
        attempts, backoff = 0, 0.5
        while not self.stopping:
            try:
                outcome = process(self.es, self.index, message.value())
                log.info("%s offset %s key %s: %s", message.topic(), message.offset(), message.key(), outcome)
                break
            except PoisonMessage as exc:
                self.dead_letter(message, exc)
                break
            except Exception as exc:
                if is_transient(exc):
                    log.warning("elasticsearch unavailable, retrying the same message: %s", exc)
                    if is_index_missing(exc):
                        self.recreate_index()
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 10)
                    continue
                attempts += 1
                log.exception("handling failed (attempt %s of %s)", attempts, MAX_ATTEMPTS)
                if attempts >= MAX_ATTEMPTS:
                    self.dead_letter(message, exc)
                    break
                time.sleep(backoff)
        else:
            return  # stopping: the offset stays uncommitted, so the message is read again on restart
        self.consumer.commit(message=message, asynchronous=False)
        self.handled += 1

    def recreate_index(self) -> None:
        try:
            ensure_index(self.es, self.index)
        except Exception as exc:  # Elasticsearch still unreachable: the retry loop tries again
            log.warning("could not recreate the search index yet: %s", exc)

    def dead_letter(self, message, exc: Exception) -> None:
        log.error("moving message to %s.dlq: %s", message.topic(), exc)
        headers = [("error", str(exc)[:500].encode()), ("original_offset", str(message.offset()).encode())]
        self.producer.produce(f"{message.topic()}.dlq", key=message.key(), value=message.value(), headers=headers)
        if self.producer.flush(10):
            # Not written, so the offset must not be committed: the message is tried again after a restart.
            raise RuntimeError("could not write to the dead-letter topic")

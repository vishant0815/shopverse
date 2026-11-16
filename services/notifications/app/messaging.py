"""The Kafka consumer: handle each message exactly once, then commit its offset.

How it fits together is described in docs/events.md. In short:
- Worker reads the topics it is subscribed to;
- process() records the message id and runs its handler in one database transaction, so a
  message handled twice (after a crash, say) is recognised and skipped;
- the Kafka offset is committed only after that transaction commits;
- a message that can never be handled, or keeps failing, goes to its topic's dead-letter twin.

Each Python service keeps its own copy of this module rather than sharing a package, so
services stay independently buildable and deployable. This copy has no outbox: the
notifications service only consumes.
"""

import json
import logging
import signal
import time
import uuid
from collections.abc import Callable

from confluent_kafka import Consumer, KafkaException, Producer
from confluent_kafka.admin import AdminClient, NewTopic
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from .models import ProcessedMessage

log = logging.getLogger(__name__)

TOPICS = ["orders.events", "payments.events", "users.events"]
MAX_ATTEMPTS = 3

Handler = Callable[[Session, dict], None]


class PoisonMessage(Exception):
    """The message can never be handled (not JSON, no id). Goes straight to the dead-letter topic."""


class Retryable(Exception):
    """Not a failure yet: the message needs something another topic will bring, so it waits
    and is tried again, up to the worker's wait limit, without counting as an attempt."""


def is_transient(exc: Exception) -> bool:
    """Errors worth waiting out (the database is down or restarting), not counted as attempts."""
    return isinstance(exc, OperationalError) or (isinstance(exc, DBAPIError) and exc.connection_invalidated)


def process(sessions: sessionmaker, handlers: dict[str, Handler], topic: str, raw: bytes) -> str:
    """Handle one message exactly once. Returns "handled", "duplicate" or "ignored"."""
    try:
        envelope = json.loads(raw)
        message_id = uuid.UUID(envelope["id"])
        type_ = envelope["type"]
    except (ValueError, KeyError, TypeError) as exc:
        raise PoisonMessage(f"unreadable message: {exc}") from exc

    handler = handlers.get(type_)
    if handler is None:
        return "ignored"  # a type this service doesn't care about

    with sessions() as db:
        db.add(ProcessedMessage(id=message_id, topic=topic, type=type_))
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return "duplicate"
        handler(db, envelope)  # raising here rolls the whole transaction back
        db.commit()
    return "handled"


def kafka_config(bootstrap: str) -> dict:
    return {"bootstrap.servers": bootstrap}


def ensure_topics(bootstrap: str, partitions: int = 3) -> None:
    """Create the topics (and their dead-letter twins) if they don't exist yet."""
    admin = AdminClient(kafka_config(bootstrap))
    wanted = TOPICS + [f"{t}.dlq" for t in TOPICS]
    existing = set(admin.list_topics(timeout=10).topics)
    missing = [NewTopic(t, num_partitions=partitions, replication_factor=1) for t in wanted if t not in existing]
    for topic, future in admin.create_topics(missing).items() if missing else []:
        try:
            future.result()
        except KafkaException as exc:
            if "TOPIC_ALREADY_EXISTS" not in str(exc):
                raise


class Worker:
    """Consume topics, handling each message once.

    wait_limit: seconds a Retryable message may wait before it is dead-lettered.
    """

    def __init__(self, *, group: str, topics: list[str], handlers: dict[str, Handler], sessions: sessionmaker,
                 bootstrap: str, wait_limit: float = 120.0, consumer=None, producer=None):
        self.group, self.topics, self.handlers, self.sessions = group, topics, handlers, sessions
        self.bootstrap = bootstrap
        self.wait_limit = wait_limit
        self.consumer = consumer
        self.producer = producer
        self.stopping = False

    def start(self):
        ensure_topics(self.bootstrap)
        self.producer = self.producer or Producer({
            **kafka_config(self.bootstrap),
            "enable.idempotence": True,
            "acks": "all",
        })
        self.consumer = self.consumer or Consumer({
            **kafka_config(self.bootstrap),
            "group.id": self.group,
            "enable.auto.commit": False,  # committed by hand, after the database commit
            "auto.offset.reset": "earliest",
        })
        self.consumer.subscribe(self.topics)
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
        signal.signal(signal.SIGINT, lambda *_: self.stop())

    def stop(self):
        self.stopping = True

    def run(self):
        self.start()
        log.info("worker %s started: consuming %s", self.group, ", ".join(self.topics))
        try:
            while not self.stopping:
                self.tick()
        finally:
            self.consumer.close()
            self.producer.flush(10)

    def tick(self, poll_timeout: float = 0.2):
        message = self.consumer.poll(poll_timeout)
        if message is None:
            return
        if message.error():
            log.warning("kafka: %s", message.error())
        else:
            self.handle(message)

    def handle(self, message):
        attempts, backoff = 0, 0.5
        waiting_since = None
        while not self.stopping:
            try:
                outcome = process(self.sessions, self.handlers, message.topic(), message.value())
                log.info("%s %s offset %s: %s", message.topic(), message.key(), message.offset(), outcome)
                break
            except PoisonMessage as exc:
                self.dead_letter(message, exc)
                break
            except Retryable as exc:
                waiting_since = waiting_since or time.monotonic()
                if time.monotonic() - waiting_since > self.wait_limit:
                    self.dead_letter(message, exc)
                    break
                log.info("waiting for contact details: %s", exc)
                time.sleep(1.0)
            except Exception as exc:
                if is_transient(exc):
                    log.warning("database unavailable, retrying the same message: %s", exc)
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
            return  # stopping: leave the offset uncommitted, the message is read again on restart
        self.consumer.commit(message=message, asynchronous=False)

    def dead_letter(self, message, exc: Exception):
        log.error("moving message to %s.dlq: %s", message.topic(), exc)
        headers = [("error", str(exc)[:500].encode()), ("original_offset", str(message.offset()).encode())]
        self.producer.produce(f"{message.topic()}.dlq", key=message.key(), value=message.value(), headers=headers)
        self.producer.flush(10)

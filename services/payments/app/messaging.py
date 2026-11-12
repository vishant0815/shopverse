"""Kafka messaging: the transactional outbox, its relay, and the consumer loop.

How it fits together is described in docs/events.md. In short:
- enqueue() adds a message to the outbox table inside the caller's database
  transaction, so the message exists if and only if the change it describes does;
- relay_pending() publishes unsent outbox rows and marks them sent;
- Worker reads topics, handles each message exactly once per message id (recorded in
  processed_messages in the same transaction as the handler's changes), and only then
  commits the Kafka offset.

Each Python service keeps its own copy of this module rather than sharing a package,
so services stay independently buildable and deployable.
"""

import json
import logging
import signal
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from confluent_kafka import Consumer, KafkaException, Producer
from confluent_kafka.admin import AdminClient, NewTopic
from sqlalchemy import BigInteger, DateTime, Identity, Index, String, Uuid, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from .db import Base

log = logging.getLogger("messaging")

SOURCE = "payments"
TOPICS = [
    "catalog.variants",
    "inventory.commands",
    "inventory.events",
    "payments.commands",
    "payments.events",
    "orders.events",
]
MAX_ATTEMPTS = 3

Handler = Callable[[Session, dict], None]


class OutboxMessage(Base):
    __tablename__ = "outbox"
    # The relay asks "what hasn't been sent?" constantly; only unsent rows are indexed,
    # so the index stays tiny however big the table grows.
    __table_args__ = (Index("ix_outbox_unsent", "seq", postgresql_where=text("published_at IS NULL")),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    # Sending order. A timestamp isn't enough: every row written in one transaction gets
    # the same now(). Messages about one order are written one transaction at a time
    # (each locks the order), so for any one key this is also the order they happened in.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    topic: Mapped[str] = mapped_column(String(100))
    key: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Null until the relay has published it.
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProcessedMessage(Base):
    """Every message id this service has handled, so a redelivered message is a no-op."""

    __tablename__ = "processed_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    topic: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(100))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def enqueue(db: Session, topic: str, type_: str, key: str, data: dict) -> OutboxMessage:
    """Add a message to the outbox. It is sent only if the caller's transaction commits."""
    message_id = uuid.uuid4()
    envelope = {
        "id": str(message_id),
        "type": type_,
        "source": SOURCE,
        "occurred_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "key": key,
        "data": data,
    }
    row = OutboxMessage(id=message_id, topic=topic, key=key, type=type_, payload=envelope)
    db.add(row)
    return row


class RelayError(Exception):
    pass


def relay_pending(sessions: sessionmaker, producer, limit: int = 200) -> int:
    """Publish unsent outbox messages in the order they were written. Returns how many."""
    with sessions() as db:
        rows = db.scalars(
            select(OutboxMessage)
            .where(OutboxMessage.published_at.is_(None))
            .order_by(OutboxMessage.seq)
            .limit(limit)
            # Two relays (say, two worker replicas) never send the same rows at once.
            .with_for_update(skip_locked=True)
        ).all()
        if not rows:
            return 0
        failures = []
        for row in rows:
            producer.produce(
                row.topic, key=row.key.encode(), value=json.dumps(row.payload).encode(),
                on_delivery=lambda err, _msg: err and failures.append(err),
            )
        unsent = producer.flush(10)
        if unsent or failures:
            db.rollback()
            raise RelayError(f"{unsent} unsent, {len(failures)} failed: {failures[:1]}")
        now = datetime.now(timezone.utc)
        for row in rows:
            row.published_at = now
        db.commit()
        return len(rows)


class PoisonMessage(Exception):
    """The message can never be handled (not JSON, no id). Goes straight to the dead-letter topic."""


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
        return "ignored"  # a type this service doesn't care about (yet)

    with sessions() as db:
        db.add(ProcessedMessage(id=message_id, topic=topic, type=type_))
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return "duplicate"
        handler(db, envelope)
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
    """Consume topics, relay the outbox, and run periodic jobs, in one loop.

    periodic: [(every_seconds, function(sessions))], e.g. a timeout sweep.
    """

    def __init__(self, *, group: str, topics: list[str], handlers: dict[str, Handler], sessions: sessionmaker,
                 bootstrap: str, periodic=(), consumer=None, producer=None):
        self.group, self.topics, self.handlers, self.sessions = group, topics, handlers, sessions
        self.bootstrap = bootstrap
        self.periodic = [[every, job, 0.0] for every, job in periodic]
        self.consumer = consumer
        self.producer = producer
        self.stopping = False

    def start(self):
        ensure_topics(self.bootstrap)
        self.producer = self.producer or Producer({
            **kafka_config(self.bootstrap),
            "enable.idempotence": True,  # retries never duplicate or reorder within a partition
            "acks": "all",
        })
        if self.topics:
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
        log.info("worker %s started: consuming %s", self.group, ", ".join(self.topics) or "nothing")
        try:
            while not self.stopping:
                self.tick()
        finally:
            if self.consumer:
                self.consumer.close()
            self.producer.flush(10)

    def tick(self, poll_timeout: float = 0.2):
        if self.consumer:
            message = self.consumer.poll(poll_timeout)
            if message is not None:
                if message.error():
                    log.warning("kafka: %s", message.error())
                else:
                    self.handle(message)
        else:
            time.sleep(poll_timeout)
        self.relay()
        now = time.monotonic()
        for job in self.periodic:
            every, function, last = job
            if now - last >= every:
                job[2] = now
                try:
                    function(self.sessions)
                except Exception:
                    log.exception("periodic job %s failed", function.__name__)

    def relay(self):
        try:
            while relay_pending(self.sessions, self.producer) == 200:
                pass  # a full batch: there may be more
        except Exception:
            log.exception("outbox relay failed; will retry")

    def handle(self, message):
        attempts, backoff = 0, 0.5
        while not self.stopping:
            try:
                outcome = process(self.sessions, self.handlers, message.topic(), message.value())
                log.info("%s %s offset %s: %s", message.topic(), message.key(), message.offset(), outcome)
                break
            except PoisonMessage as exc:
                self.dead_letter(message, exc)
                break
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

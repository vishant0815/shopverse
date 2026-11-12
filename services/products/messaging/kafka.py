"""Kafka messaging: the transactional outbox, its relay, and the consumer loop.

How it fits together is described in docs/events.md. In short:
- enqueue() adds a message to the outbox table inside the caller's database
  transaction, so the message exists if and only if the change it describes does;
- relay_pending() publishes unsent outbox rows and marks them sent;
- Worker reads topics, handles each message exactly once per message id (recorded in
  processed_messages in the same transaction as the handler's changes), and only then
  commits the Kafka offset.

Each Django service keeps its own copy of this app (orders and products), and the
FastAPI services have the same logic in app/messaging.py, so every service stays
independently buildable and deployable.
"""

import json
import logging
import signal
import time
import uuid
from collections.abc import Callable

from confluent_kafka import Consumer, KafkaException, Producer
from confluent_kafka.admin import AdminClient, NewTopic
from django.conf import settings
from django.db import IntegrityError, InterfaceError, OperationalError, close_old_connections, transaction
from django.utils import timezone

from .models import OutboxMessage, ProcessedMessage

log = logging.getLogger("messaging")

TOPICS = [
    "catalog.variants",
    "inventory.commands",
    "inventory.events",
    "payments.commands",
    "payments.events",
    "orders.events",
]
MAX_ATTEMPTS = 3
BATCH = 200

Handler = Callable[[dict], None]


def enqueue(topic: str, type_: str, key: str, data: dict) -> OutboxMessage:
    """Add a message to the outbox. Call inside the transaction that makes the change:
    the message is then sent only if that transaction commits."""
    message_id = uuid.uuid4()
    envelope = {
        "id": str(message_id),
        "type": type_,
        "source": settings.MESSAGING["SOURCE"],
        "occurred_at": timezone.now().isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "key": key,
        "data": data,
    }
    return OutboxMessage.objects.create(message_id=message_id, topic=topic, key=key, type=type_, payload=envelope)


class RelayError(Exception):
    pass


def relay_pending(producer, limit: int = BATCH) -> int:
    """Publish unsent outbox messages in the order they were written. Returns how many."""
    with transaction.atomic():
        # skip_locked: two relays (say, two worker replicas) never send the same rows at once.
        rows = list(
            OutboxMessage.objects.select_for_update(skip_locked=True)
            .filter(published_at__isnull=True)
            .order_by("seq")[:limit]
        )
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
            raise RelayError(f"{unsent} unsent, {len(failures)} failed: {failures[:1]}")
        OutboxMessage.objects.filter(seq__in=[row.seq for row in rows]).update(published_at=timezone.now())
        return len(rows)


class PoisonMessage(Exception):
    """The message can never be handled (not JSON, no id). Goes straight to the dead-letter topic."""


def is_transient(exc: Exception) -> bool:
    """Errors worth waiting out (the database is down or restarting), not counted as attempts."""
    return isinstance(exc, (OperationalError, InterfaceError))


def process(handlers: dict[str, Handler], topic: str, raw: bytes) -> str:
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

    try:
        with transaction.atomic():
            ProcessedMessage.objects.create(id=message_id, topic=topic, type=type_)
            handler(envelope)
    except IntegrityError:
        # Either the id was seen before, or the handler broke a constraint. Tell them apart.
        if ProcessedMessage.objects.filter(id=message_id).exists():
            return "duplicate"
        raise
    return "handled"


def kafka_config() -> dict:
    return {"bootstrap.servers": settings.MESSAGING["BOOTSTRAP_SERVERS"]}


def ensure_topics(partitions: int = 3) -> None:
    """Create the topics (and their dead-letter twins) if they don't exist yet."""
    admin = AdminClient(kafka_config())
    wanted = TOPICS + [f"{t}.dlq" for t in TOPICS]
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


class Worker:
    """Consume topics, relay the outbox, and run periodic jobs, in one loop.

    periodic: [(every_seconds, function())], e.g. a timeout sweep.
    """

    def __init__(self, *, group: str, topics: list[str], handlers: dict[str, Handler], periodic=(),
                 consumer=None, producer=None):
        self.group, self.topics, self.handlers = group, topics, handlers
        self.periodic = [[every, job, 0.0] for every, job in periodic]
        self.consumer = consumer
        self.producer = producer
        self.stopping = False

    def start(self):
        ensure_topics()
        self.producer = self.producer or Producer({
            **kafka_config(),
            "enable.idempotence": True,  # retries never duplicate or reorder within a partition
            "acks": "all",
        })
        if self.topics:
            self.consumer = self.consumer or Consumer({
                **kafka_config(),
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
        close_old_connections()  # a long-running loop must drop connections the database closed
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
                    function()
                except Exception:
                    log.exception("periodic job %s failed", function.__name__)

    def relay(self):
        try:
            while relay_pending(self.producer) == BATCH:
                pass  # a full batch: there may be more
        except Exception:
            log.exception("outbox relay failed; will retry")

    def handle(self, message):
        attempts, backoff = 0, 0.5
        while not self.stopping:
            try:
                outcome = process(self.handlers, message.topic(), message.value())
                log.info("%s %s offset %s: %s", message.topic(), message.key(), message.offset(), outcome)
                break
            except PoisonMessage as exc:
                self.dead_letter(message, exc)
                break
            except Exception as exc:
                if is_transient(exc):
                    log.warning("database unavailable, retrying the same message: %s", exc)
                    close_old_connections()
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

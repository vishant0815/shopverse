"""The consumer loop: what happens to a message, and when its offset is committed."""

import json
import uuid

from app.handlers import RecipientUnknown
from app.messaging import MAX_ATTEMPTS, Worker
from app.db import get_sessionmaker

from .conftest import CUSTOMER


class FakeMessage:
    def __init__(self, topic, value, key=b"k", offset=7):
        self._topic, self._value, self._key, self._offset = topic, value, key, offset

    def topic(self):
        return self._topic

    def value(self):
        return self._value

    def key(self):
        return self._key

    def offset(self):
        return self._offset

    def error(self):
        return None


class FakeConsumer:
    def __init__(self):
        self.commits = []

    def commit(self, message, asynchronous):
        self.commits.append(message.offset())


class FakeProducer:
    def __init__(self):
        self.produced = []

    def produce(self, topic, key, value, headers):
        self.produced.append((topic, value, dict(headers)))

    def flush(self, timeout):
        return 0


def worker(handlers, *, wait_limit=120.0):
    consumer, producer = FakeConsumer(), FakeProducer()
    return Worker(
        group="test", topics=["orders.events"], handlers=handlers, sessions=get_sessionmaker(),
        bootstrap="unused", wait_limit=wait_limit, consumer=consumer, producer=producer,
    ), consumer, producer


def message_bytes(type_, data):
    return json.dumps({
        "id": str(uuid.uuid4()), "type": type_, "source": "test", "occurred_at": "2026-11-16T10:00:00.000Z",
        "key": "k", "data": data,
    }).encode()


def test_a_handled_message_has_its_offset_committed_and_nothing_dead_lettered(handlers, mailer, customer_registered):
    w, consumer, producer = worker(handlers)
    w.handle(FakeMessage("users.events", message_bytes("UserContactChanged", {
        "user_id": str(CUSTOMER), "email": "again@example.com", "first_name": "Nia", "last_name": "Khan",
    }), offset=11))

    assert consumer.commits == [11]
    assert producer.produced == []


def test_a_message_that_is_not_json_goes_straight_to_the_dead_letter_topic(handlers):
    w, consumer, producer = worker(handlers)
    w.handle(FakeMessage("orders.events", b"not json at all", offset=3))

    [(topic, value, headers)] = producer.produced
    assert topic == "orders.events.dlq"
    assert value == b"not json at all"
    assert headers["original_offset"] == b"3"
    assert consumer.commits == [3]


def test_a_customer_that_never_appears_is_dead_lettered_after_the_wait_limit(handlers):
    w, consumer, producer = worker(handlers, wait_limit=0.0)
    w.handle(FakeMessage("orders.events", message_bytes("OrderPlaced", {
        "order_number": "SV-Y", "user_id": str(CUSTOMER), "total": "1.00", "currency": "GBP", "items": [],
    }), offset=5))

    [(topic, _, headers)] = producer.produced
    assert topic == "orders.events.dlq"
    assert headers["error"].decode().startswith("no contact details")
    assert consumer.commits == [5]


def test_a_failing_handler_is_retried_then_dead_lettered(handlers, monkeypatch):
    attempts = []

    def broken(db, envelope):
        attempts.append(envelope["id"])
        raise ValueError("bad data")

    monkeypatch.setitem(handlers, "OrderCancelled", broken)
    monkeypatch.setattr("app.messaging.time.sleep", lambda seconds: None)
    w, consumer, producer = worker(handlers)
    w.handle(FakeMessage("orders.events", message_bytes("OrderCancelled", {"order_number": "SV-Z"}), offset=9))

    assert len(attempts) == MAX_ATTEMPTS
    assert producer.produced[0][0] == "orders.events.dlq"
    assert consumer.commits == [9]


def test_a_retryable_error_is_not_counted_as_an_attempt(handlers, monkeypatch):
    calls = []

    def wait_then_succeed(db, envelope):
        calls.append(1)
        if len(calls) < 5:
            raise RecipientUnknown("not yet")

    monkeypatch.setitem(handlers, "OrderCancelled", wait_then_succeed)
    monkeypatch.setattr("app.messaging.time.sleep", lambda seconds: None)
    w, consumer, producer = worker(handlers)
    w.handle(FakeMessage("orders.events", message_bytes("OrderCancelled", {"order_number": "SV-W"}), offset=2))

    assert len(calls) == 5  # more tries than MAX_ATTEMPTS, and still handled
    assert producer.produced == []
    assert consumer.commits == [2]

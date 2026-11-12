"""The outbox, relay and consumer loop, with Kafka replaced by small fakes."""

import json
import uuid

import pytest
from django.db import OperationalError

from messaging.kafka import PoisonMessage, Worker, enqueue, process, relay_pending
from messaging.models import OutboxMessage, ProcessedMessage

pytestmark = pytest.mark.django_db(transaction=True)


class FakeProducer:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def produce(self, topic, key=None, value=None, on_delivery=None, headers=None):
        self.sent.append({"topic": topic, "key": key, "value": value, "headers": headers})
        if on_delivery:
            on_delivery("broker down" if self.fail else None, None)

    def flush(self, timeout=None):
        return 0


class FakeMessage:
    def __init__(self, value, topic="inventory.events", key=b"SV-1", offset=7):
        self._value, self._topic, self._key, self._offset = value, topic, key, offset

    def value(self): return self._value
    def topic(self): return self._topic
    def key(self): return self._key
    def offset(self): return self._offset
    def error(self): return None


class FakeConsumer:
    def __init__(self):
        self.committed = []

    def commit(self, message=None, asynchronous=True):
        self.committed.append(message.offset())


def raw(type_, data=None, message_id=None):
    return json.dumps({"id": str(message_id or uuid.uuid4()), "type": type_, "source": "test",
                       "occurred_at": "2026-11-12T10:00:00.000Z", "key": "SV-1", "data": data or {}}).encode()


def worker(handlers):
    return Worker(group="test", topics=["inventory.events"], handlers=handlers,
                  consumer=FakeConsumer(), producer=FakeProducer())


def test_enqueue_writes_a_full_envelope():
    row = enqueue("inventory.commands", "ReserveStock", "SV-1", {"order_number": "SV-1"})

    assert row.payload["id"] == str(row.message_id)
    assert row.payload["source"] == "orders"
    assert row.payload["occurred_at"].endswith("Z")
    assert row.payload["data"] == {"order_number": "SV-1"}
    assert row.published_at is None


def test_the_relay_publishes_in_order_and_marks_rows_sent():
    for n in range(3):
        enqueue("inventory.commands", "ReserveStock", f"SV-{n}", {"n": n})
    producer = FakeProducer()

    assert relay_pending(producer) == 3
    assert relay_pending(producer) == 0

    assert [json.loads(m["value"])["data"]["n"] for m in producer.sent] == [0, 1, 2]
    assert not OutboxMessage.objects.filter(published_at__isnull=True).exists()


def test_if_kafka_refuses_the_rows_stay_unsent():
    enqueue("inventory.commands", "ReserveStock", "SV-1", {})

    with pytest.raises(Exception):
        relay_pending(FakeProducer(fail=True))

    assert OutboxMessage.objects.get().published_at is None


def test_a_message_is_handled_once_per_id():
    calls = []
    message_id = uuid.uuid4()
    handlers = {"Ping": lambda msg: calls.append(msg["id"])}

    assert process(handlers, "t", raw("Ping", message_id=message_id)) == "handled"
    assert process(handlers, "t", raw("Ping", message_id=message_id)) == "duplicate"

    assert len(calls) == 1
    assert ProcessedMessage.objects.get(id=message_id).type == "Ping"


def test_unknown_types_are_ignored_and_junk_is_poison():
    assert process({}, "t", raw("SomethingNew")) == "ignored"
    with pytest.raises(PoisonMessage):
        process({}, "t", b"not json")


def test_a_failing_handler_leaves_no_trace():
    message_id = uuid.uuid4()

    def handler(msg):
        enqueue("inventory.commands", "Half", "SV-1", {})
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        process({"Ping": handler}, "t", raw("Ping", message_id=message_id))

    assert not ProcessedMessage.objects.filter(id=message_id).exists()
    assert not OutboxMessage.objects.exists()


def test_the_offset_is_committed_after_handling():
    w = worker({"Ping": lambda msg: None})

    w.handle(FakeMessage(raw("Ping")))

    assert w.consumer.committed == [7]


def test_a_message_that_keeps_failing_is_dead_lettered(monkeypatch):
    monkeypatch.setattr("messaging.kafka.time.sleep", lambda s: None)
    calls = []

    def handler(msg):
        calls.append(1)
        raise ValueError("bad data")

    w = worker({"Ping": handler})
    w.handle(FakeMessage(raw("Ping")))

    assert len(calls) == 3
    assert w.producer.sent[0]["topic"] == "inventory.events.dlq"
    assert w.consumer.committed == [7]


def test_a_database_outage_is_waited_out(monkeypatch):
    monkeypatch.setattr("messaging.kafka.time.sleep", lambda s: None)
    calls = []

    def handler(msg):
        calls.append(1)
        if len(calls) <= 4:
            raise OperationalError("connection refused")

    w = worker({"Ping": handler})
    w.handle(FakeMessage(raw("Ping")))

    assert len(calls) == 5
    assert w.producer.sent == []
    assert w.consumer.committed == [7]

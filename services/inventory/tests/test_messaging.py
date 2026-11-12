"""The outbox, relay and consumer loop, with Kafka replaced by small fakes."""

import json
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.messaging import OutboxMessage, PoisonMessage, ProcessedMessage, Worker, enqueue, process, relay_pending

from .conftest import envelope


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
    def __init__(self, value, topic="inventory.commands", key=b"SV-1", offset=7):
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


def raw(type_, data, message_id=None):
    return json.dumps(envelope(type_, data, message_id=message_id)).encode()


# Outbox and relay ----------------------------------------------------------------------

def test_enqueue_writes_a_full_envelope(sessions):
    with sessions() as db:
        enqueue(db, "inventory.events", "StockReserved", "SV-1", {"order_number": "SV-1"})
        db.commit()
        row = db.scalar(select(OutboxMessage))

    assert row.topic == "inventory.events"
    assert row.key == "SV-1"
    assert row.published_at is None
    assert row.payload["id"] == str(row.id)
    assert row.payload["type"] == "StockReserved"
    assert row.payload["source"] == "inventory"
    assert row.payload["occurred_at"].endswith("Z")
    assert row.payload["data"] == {"order_number": "SV-1"}


def test_nothing_is_sent_if_the_transaction_rolls_back(sessions):
    with sessions() as db:
        enqueue(db, "inventory.events", "StockReserved", "SV-1", {})
        db.rollback()
        assert db.scalar(select(OutboxMessage)) is None


def test_the_relay_publishes_in_order_and_marks_rows_sent(sessions):
    with sessions() as db:
        for n in range(3):
            enqueue(db, "inventory.events", "StockReserved", f"SV-{n}", {"n": n})
            db.flush()
        db.commit()
    producer = FakeProducer()

    assert relay_pending(sessions, producer) == 3
    assert relay_pending(sessions, producer) == 0  # nothing left

    assert [json.loads(m["value"])["data"]["n"] for m in producer.sent] == [0, 1, 2]
    assert [m["key"] for m in producer.sent] == [b"SV-0", b"SV-1", b"SV-2"]
    with sessions() as db:
        assert all(row.published_at for row in db.scalars(select(OutboxMessage)))


def test_if_kafka_refuses_the_rows_stay_unsent(sessions):
    with sessions() as db:
        enqueue(db, "inventory.events", "StockReserved", "SV-1", {})
        db.commit()

    with pytest.raises(Exception):
        relay_pending(sessions, FakeProducer(fail=True))

    with sessions() as db:
        assert db.scalar(select(OutboxMessage)).published_at is None


# Handling a message --------------------------------------------------------------------

def test_a_handled_message_is_recorded(sessions):
    message_id = uuid.uuid4()
    handlers = {"Ping": lambda db, msg: None}

    assert process(sessions, handlers, "t", raw("Ping", {}, message_id)) == "handled"

    with sessions() as db:
        assert db.get(ProcessedMessage, message_id).type == "Ping"


def test_types_without_a_handler_are_ignored(sessions):
    assert process(sessions, {}, "t", raw("SomethingNew", {})) == "ignored"


@pytest.mark.parametrize("bad", [b"not json", b"{}", json.dumps({"id": "nope", "type": "X"}).encode()])
def test_unreadable_messages_are_poison(sessions, bad):
    with pytest.raises(PoisonMessage):
        process(sessions, {}, "t", bad)


def test_a_failing_handler_leaves_no_trace(sessions):
    message_id = uuid.uuid4()

    def handler(db, msg):
        enqueue(db, "inventory.events", "Half", "SV-1", {})
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        process(sessions, {"Ping": handler}, "t", raw("Ping", {}, message_id))

    with sessions() as db:
        assert db.get(ProcessedMessage, message_id) is None  # so it will be tried again
        assert db.scalar(select(OutboxMessage)) is None


# The worker loop -----------------------------------------------------------------------

def worker(sessions, handlers):
    w = Worker(group="test", topics=["inventory.commands"], handlers=handlers, sessions=sessions,
               bootstrap="unused", consumer=FakeConsumer(), producer=FakeProducer())
    return w


def test_the_offset_is_committed_after_handling(sessions, monkeypatch):
    w = worker(sessions, {"Ping": lambda db, msg: None})

    w.handle(FakeMessage(raw("Ping", {})))

    assert w.consumer.committed == [7]
    assert w.producer.sent == []


def test_poison_goes_to_the_dead_letter_topic(sessions):
    w = worker(sessions, {})

    w.handle(FakeMessage(b"not json"))

    assert w.consumer.committed == [7]
    [dead] = w.producer.sent
    assert dead["topic"] == "inventory.commands.dlq"
    assert dead["value"] == b"not json"
    assert dict(dead["headers"])["original_offset"] == b"7"


def test_a_message_that_keeps_failing_goes_to_dead_letter_after_three_tries(sessions, monkeypatch):
    monkeypatch.setattr("app.messaging.time.sleep", lambda s: None)
    calls = []

    def handler(db, msg):
        calls.append(1)
        raise ValueError("bad data")

    w = worker(sessions, {"Ping": handler})
    w.handle(FakeMessage(raw("Ping", {})))

    assert len(calls) == 3
    assert w.producer.sent[0]["topic"] == "inventory.commands.dlq"
    assert dict(w.producer.sent[0]["headers"])["error"] == b"bad data"
    assert w.consumer.committed == [7]


def test_a_database_outage_is_waited_out_not_dead_lettered(sessions, monkeypatch):
    monkeypatch.setattr("app.messaging.time.sleep", lambda s: None)
    calls = []

    def handler(db, msg):
        calls.append(1)
        if len(calls) <= 5:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    w = worker(sessions, {"Ping": handler})
    w.handle(FakeMessage(raw("Ping", {})))

    assert len(calls) == 6
    assert w.producer.sent == []
    assert w.consumer.committed == [7]


def test_stopping_mid_retry_leaves_the_offset_uncommitted(sessions, monkeypatch):
    w = worker(sessions, {})

    def handler(db, msg):
        w.stop()
        raise OperationalError("SELECT 1", {}, Exception("down"))

    w.handlers = {"Ping": handler}
    monkeypatch.setattr("app.messaging.time.sleep", lambda s: None)
    w.handle(FakeMessage(raw("Ping", {})))

    assert w.consumer.committed == []

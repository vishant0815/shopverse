"""The Kafka path: a real topic, a real consumer loop, and the dead-letter topic."""

import threading
import time
import uuid

import pytest
from confluent_kafka import Consumer, Producer

from app.config import get_settings
from app.consumer import SearchConsumer, ensure_topics

from .test_index import stored


def wait_until(predicate, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.3)
    raise AssertionError("timed out waiting for the search consumer")


@pytest.fixture
def topic():
    """A topic of this test's own, so earlier tests' messages are never replayed into it."""
    name = f"catalog.products.test-{uuid.uuid4().hex[:8]}"
    ensure_topics(get_settings().kafka_bootstrap_servers, [name])
    return name


@pytest.fixture
def running_consumer(es, index, topic):
    settings = get_settings()
    consumer = SearchConsumer(
        es=es, index=index, bootstrap=settings.kafka_bootstrap_servers,
        group=f"search-test-{uuid.uuid4().hex[:8]}", topics=[topic],
    )
    thread = threading.Thread(target=consumer.run, daemon=True)
    thread.start()
    yield consumer
    consumer.stop()
    thread.join(timeout=20)


@pytest.fixture
def send_to_topic(topic):
    producer = Producer({"bootstrap.servers": get_settings().kafka_bootstrap_servers,
                         "enable.idempotence": True, "acks": "all"})

    def send_to_topic(messages):
        for key, value in messages:
            producer.produce(topic, key=key.encode(), value=value)
        assert producer.flush(10) == 0

    return send_to_topic


def test_consumer_applies_messages_including_out_of_order_ones(
        running_consumer, send_to_topic, make_product, envelope, es, index):
    shop = make_product("Navy Shirt", revision=1)
    newer = make_product("Navy Shirt, new", product_id=shop["product_id"], revision=2)
    gone = make_product("Discontinued", revision=1)

    send_to_topic([
        (shop["product_id"], envelope("ProductUpserted", newer)),
        (shop["product_id"], envelope("ProductUpserted", shop)),  # older revision arrives last
        (gone["product_id"], envelope("ProductUpserted", gone)),
        (gone["product_id"], envelope("ProductRemoved", {"product_id": gone["product_id"]})),
    ])
    wait_until(lambda: running_consumer.handled == 4)
    es.indices.refresh(index=index)

    doc = stored(es, index, shop["product_id"])
    assert doc["_source"]["name"] == "Navy Shirt, new"
    assert doc["_version"] == 2
    assert stored(es, index, gone["product_id"]) is None


def test_poison_message_goes_to_the_dead_letter_topic_and_the_consumer_carries_on(
        running_consumer, send_to_topic, topic, make_product, envelope, es, index):
    poison = b"this is not json"
    product = make_product("After the poison", revision=1)
    send_to_topic([("bad", poison), (product["product_id"], envelope("ProductUpserted", product))])

    wait_until(lambda: running_consumer.handled == 2)
    es.indices.refresh(index=index)

    assert stored(es, index, product["product_id"])["_source"]["name"] == "After the poison"

    dead = Consumer({"bootstrap.servers": get_settings().kafka_bootstrap_servers,
                     "group.id": f"dlq-test-{uuid.uuid4().hex[:8]}", "auto.offset.reset": "earliest",
                     "enable.auto.commit": False})
    dead.subscribe([f"{topic}.dlq"])
    found = None
    deadline = time.monotonic() + 30
    try:
        while found is None and time.monotonic() < deadline:
            message = dead.poll(1.0)
            if message is not None and not message.error() and message.value() == poison:
                found = message
    finally:
        dead.close()

    assert found is not None
    headers = dict(found.headers())
    assert b"unreadable message" in headers["error"]
    assert headers["original_offset"] == b"0"


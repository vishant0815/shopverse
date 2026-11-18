import json
import uuid

import pytest
from pyspark.sql import SparkSession


@pytest.fixture(scope="session")
def spark():
    session = (
        SparkSession.builder.master("local[2]")
        .appName("clickstream-tests")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
    session.sparkContext.setLogLevel("ERROR")
    yield session
    session.stop()


def click(at: str, type_: str, event_id=None, session="session-1", **fields) -> str:
    """One storefront event as the collector writes it to Kafka."""
    event = {
        "event_id": event_id or str(uuid.uuid4()),
        "type": type_,
        "occurred_at": at,
        "received_at": at,
        "session_id": session,
        "user_id": None,
    } | fields
    return json.dumps(event)


def order_confirmed(at: str, items: list[tuple[str, int]], event_id=None) -> str:
    """An OrderConfirmed message: the envelope from docs/events.md around the order data."""
    return json.dumps({
        "id": event_id or str(uuid.uuid4()),
        "type": "OrderConfirmed",
        "source": "orders",
        "occurred_at": at,
        "key": "ORD-1",
        "data": {
            "order_number": "ORD-1",
            "user_id": None,
            "total": "0.00",
            "currency": "GBP",
            "items": [{"product_id": pid, "quantity": qty, "name": "Lamp"} for pid, qty in items],
        },
    })


def order_placed(at: str, items: list[tuple[str, int]]) -> str:
    """A message on the same topic that the job must ignore."""
    return order_confirmed(at, items).replace("OrderConfirmed", "OrderPlaced")

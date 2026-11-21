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


def product_upserted(product_id: str, seller_id: str, name: str, revision: int = 1) -> str:
    """A ProductUpserted message from the catalogue (its outbox envelope around the product document)."""
    return json.dumps({
        "id": str(uuid.uuid4()),
        "type": "ProductUpserted",
        "source": "products",
        "occurred_at": "2026-11-18T09:00:00.000Z",
        "key": product_id,
        "data": {
            "product_id": product_id,
            "revision": revision,
            "listed": True,
            "seller_id": seller_id,
            "slug": name.lower().replace(" ", "-"),
            "name": name,
            "image_url": "",
            "status": "active",
        },
    })

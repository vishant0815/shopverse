"""Test setup. The tests run against the real Elasticsearch and Kafka, in their own index and topics.

Each run gets a fresh index and each Kafka test a fresh topic, so nothing here touches the real
products index or the real catalogue topic.
"""

import json
import os
import uuid

RUN = uuid.uuid4().hex[:8]
os.environ.setdefault("ES_URL", "http://127.0.0.1:9200")
os.environ["SEARCH_INDEX"] = f"products_test_{RUN}"
os.environ["PRODUCTS_TOPIC"] = f"catalog.products.test-{RUN}"
os.environ["KAFKA_GROUP"] = f"search-test-{RUN}"

import pytest  # noqa: E402
from elasticsearch import Elasticsearch  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.index import ensure_index  # noqa: E402
from app.indexer import process  # noqa: E402


@pytest.fixture(scope="session")
def es():
    client = Elasticsearch(get_settings().es_url)
    yield client
    client.close()


@pytest.fixture(scope="session", autouse=True)
def index(es):
    name = get_settings().search_index
    ensure_index(es, name)
    yield name
    es.indices.delete(index=name, ignore_unavailable=True)


@pytest.fixture(autouse=True)
def clean_index(es, index):
    yield
    es.delete_by_query(index=index, query={"match_all": {}}, refresh=True, conflicts="proceed")


@pytest.fixture
def envelope():
    """envelope(type, data) -> the bytes of a Kafka message, as the products service sends them."""
    def envelope(type_, data):
        return json.dumps({
            "id": str(uuid.uuid4()), "type": type_, "source": "test", "occurred_at": "2026-11-12T10:00:00.000Z",
            "key": data.get("product_id"), "data": data,
        }).encode()

    return envelope


@pytest.fixture
def make_product():
    """make_product(name, ...) -> a ProductUpserted payload shaped like the products service's."""
    def make_product(name="Cotton Shirt", *, product_id=None, revision=1, listed=True, price_min="10.00",
                     price_max="20.00", colours=("Navy",), sizes=("M",), categories=(("clothing", "Clothing"),),
                     brand="Acme", created_at="2026-11-01T10:00:00+00:00", **overrides):
        leaf_slug, leaf_name = categories[-1]
        data = {
            "product_id": product_id or str(uuid.uuid4()),
            "revision": revision,
            "listed": listed,
            "seller_id": str(uuid.uuid4()),
            "slug": name.lower().replace(" ", "-"),
            "name": name,
            "brand": brand,
            "description": f"{name}, a test product.",
            "status": "active" if listed else "draft",
            "category": {"id": str(uuid.uuid4()), "name": leaf_name, "slug": leaf_slug},
            "category_slugs": [slug for slug, _ in categories],
            "category_names": [label for _, label in categories],
            "image_url": "https://example.test/image.jpg",
            "images": [{"url": "https://example.test/image.jpg", "alt_text": name}],
            "variants": [],
            "colours": list(colours),
            "sizes": list(sizes),
            "price_min": price_min,
            "price_max": price_max,
            "created_at": created_at,
            "updated_at": created_at,
        }
        data.update(overrides)
        return data

    return make_product


@pytest.fixture
def publish(es, index, envelope):
    """publish(*products) indexes ProductUpserted messages, then makes them searchable."""
    def publish(*products):
        for product in products:
            process(es, index, envelope("ProductUpserted", product))
        es.indices.refresh(index=index)

    return publish

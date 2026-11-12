import pytest
from elasticsearch import NotFoundError

from app.index import ensure_index
from app.indexer import PoisonMessage, process


def stored(es, index, product_id):
    try:
        return es.get(index=index, id=product_id)
    except NotFoundError:
        return None


def test_ensure_index_can_be_repeated(es, index):
    ensure_index(es, index)
    ensure_index(es, index)
    mapping = es.indices.get_mapping(index=index)[index]["mappings"]
    assert mapping["dynamic"] == "strict"
    assert mapping["properties"]["suggest"]["type"] == "completion"


def test_listed_product_is_indexed_at_its_revision(es, index, make_product, envelope):
    product = make_product("Navy Cotton Shirt", revision=1)

    assert process(es, index, envelope("ProductUpserted", product)) == "indexed"

    doc = stored(es, index, product["product_id"])
    assert doc["_version"] == 1
    assert doc["_source"]["listed"] is True
    assert doc["_source"]["suggest"]["input"] == ["Navy Cotton Shirt", "Acme"]
    assert "revision" not in doc["_source"]


def test_newer_revision_replaces_the_older_one(es, index, make_product, envelope):
    first = make_product("Old name", revision=1)
    second = make_product("New name", product_id=first["product_id"], revision=2)

    process(es, index, envelope("ProductUpserted", first))
    assert process(es, index, envelope("ProductUpserted", second)) == "indexed"

    doc = stored(es, index, first["product_id"])
    assert doc["_source"]["name"] == "New name"
    assert doc["_version"] == 2


def test_stale_and_repeated_messages_change_nothing(es, index, make_product, envelope):
    newer = make_product("New name", revision=2)
    older = make_product("Old name", product_id=newer["product_id"], revision=1)

    process(es, index, envelope("ProductUpserted", newer))

    assert process(es, index, envelope("ProductUpserted", older)) == "stale"
    assert process(es, index, envelope("ProductUpserted", newer)) == "stale"  # redelivery
    assert stored(es, index, newer["product_id"])["_source"]["name"] == "New name"


def test_unlisted_product_is_kept_with_listed_false(es, index, make_product, envelope):
    live = make_product("Shirt", revision=1)
    hidden = {**live, "revision": 2, "listed": False, "status": "draft"}

    process(es, index, envelope("ProductUpserted", live))
    assert process(es, index, envelope("ProductUpserted", hidden)) == "unlisted"

    doc = stored(es, index, live["product_id"])
    assert doc["_version"] == 2
    assert doc["_source"]["listed"] is False
    assert "suggest" not in doc["_source"]


def test_older_listed_message_cannot_bring_back_an_unlisted_product(es, index, make_product, envelope):
    live = make_product("Shirt", revision=1)
    hidden = {**live, "revision": 2, "listed": False}

    process(es, index, envelope("ProductUpserted", hidden))

    assert process(es, index, envelope("ProductUpserted", live)) == "stale"
    assert stored(es, index, live["product_id"])["_source"]["listed"] is False


def test_product_without_an_active_option_is_not_listed(es, index, make_product, envelope):
    product = make_product("Sold out shirt", revision=1, price_min=None, price_max=None)

    assert process(es, index, envelope("ProductUpserted", product)) == "unlisted"


def test_removed_product_is_deleted_and_removing_twice_is_harmless(es, index, make_product, envelope):
    product = make_product("Shirt", revision=1)
    removal = envelope("ProductRemoved", {"product_id": product["product_id"]})
    process(es, index, envelope("ProductUpserted", product))

    assert process(es, index, removal) == "removed"
    assert stored(es, index, product["product_id"]) is None
    assert process(es, index, removal) == "removed"


def test_unreadable_or_incomplete_messages_are_poison(es, index, make_product, envelope):
    product = make_product("Shirt", revision=1)
    missing_name = {key: value for key, value in product.items() if key != "name"}

    with pytest.raises(PoisonMessage):
        process(es, index, b"not json")
    with pytest.raises(PoisonMessage):
        process(es, index, envelope("ProductUpserted", missing_name))
    with pytest.raises(PoisonMessage):
        process(es, index, envelope("ProductUpserted", {**product, "revision": 0}))
    with pytest.raises(PoisonMessage):
        process(es, index, envelope("ProductRemoved", {}))


def test_other_message_types_are_ignored(es, index, envelope):
    assert process(es, index, envelope("VariantUpserted", {"variant_id": "x"})) == "ignored"

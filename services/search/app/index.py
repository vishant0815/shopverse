"""The product index: its mapping, and how a catalogue announcement is written to it.

One document per product. Each ProductUpserted carries the product's revision, and that
revision is the document's version (external versioning): a write with an older or equal
revision is refused with a conflict, so duplicate and out-of-date messages change nothing.

Unlisted products stay in the index with listed=false rather than being deleted. Deleting
would forget the revision, and an older listed message arriving later could bring a hidden
product back. Every search filters on listed=true. Only ProductRemoved (the product was
deleted from the catalogue) removes a document.
"""

from elasticsearch import ApiError, ConflictError, Elasticsearch, NotFoundError

MAPPING = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "product_id": {"type": "keyword"},
            "seller_id": {"type": "keyword"},
            "slug": {"type": "keyword"},
            "name": {"type": "text"},
            "brand": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
            "description": {"type": "text"},
            "status": {"type": "keyword"},
            "listed": {"type": "boolean"},
            "category": {"properties": {
                "id": {"type": "keyword"},
                "name": {"type": "keyword"},
                "slug": {"type": "keyword"},
            }},
            # The category and every category above it, so a search under "clothing" finds shirts.
            "category_slugs": {"type": "keyword"},
            "category_names": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
            "colours": {"type": "keyword"},
            "sizes": {"type": "keyword"},
            "price_min": {"type": "scaled_float", "scaling_factor": 100},
            "price_max": {"type": "scaled_float", "scaling_factor": 100},
            "image_url": {"type": "keyword", "index": False},
            "images": {"type": "object", "enabled": False},
            "variants": {"type": "object", "enabled": False},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "suggest": {"type": "completion"},
        },
    },
}

DOCUMENT_FIELDS = (
    "product_id", "seller_id", "slug", "name", "brand", "description", "status", "category",
    "category_slugs", "category_names", "colours", "sizes", "price_min", "price_max", "image_url",
    "images", "variants", "created_at", "updated_at",
)


def ensure_index(es: Elasticsearch, name: str) -> None:
    """Create the index if it doesn't exist. Safe when several processes start at once."""
    if es.indices.exists(index=name):
        return
    try:
        es.indices.create(index=name, **MAPPING)
    except ApiError:
        # Another process created it between the check and the create.
        if not es.indices.exists(index=name):
            raise


def document(data: dict) -> dict:
    """The indexed form of a ProductUpserted payload. Raises KeyError if a field is missing."""
    listed = bool(data["listed"]) and data["price_min"] is not None  # no active option, nothing to buy
    doc = {key: data[key] for key in DOCUMENT_FIELDS}
    doc["listed"] = listed
    if listed:
        # Autosuggest only offers listed products: only they have a suggest entry.
        inputs = [text for text in (data["name"], data["brand"]) if text]
        doc["suggest"] = {"input": inputs, "weight": 1}
    return doc


def write(es: Elasticsearch, index: str, product_id: str, revision: int, doc: dict) -> str:
    """Store the document at its revision. Returns "indexed", "unlisted" or "stale"."""
    try:
        es.index(index=index, id=product_id, document=doc, version=revision, version_type="external")
    except ConflictError:
        return "stale"  # the index already holds this revision or a newer one
    return "indexed" if doc["listed"] else "unlisted"


def remove(es: Elasticsearch, index: str, product_id: str) -> str:
    try:
        es.delete(index=index, id=product_id)
    except NotFoundError:
        pass  # already gone: removing twice is harmless
    return "removed"

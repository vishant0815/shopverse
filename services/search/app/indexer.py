"""Applies one catalogue message to the search index.

Messages use the same envelope as every other service: {id, type, source, occurred_at, key, data}.
Idempotency comes from the index itself (the revision is the document version), so this module
keeps no table of handled message ids.
"""

import json

from elasticsearch import Elasticsearch

from .index import document, remove, write


class PoisonMessage(Exception):
    """The message can never be applied (not JSON, or fields missing). Goes straight to the dead-letter topic."""


def process(es: Elasticsearch, index: str, raw: bytes) -> str:
    """Apply one message. Returns "indexed", "unlisted", "stale", "removed" or "ignored"."""
    try:
        envelope = json.loads(raw)
        type_ = envelope["type"]
        data = envelope["data"]
    except (ValueError, KeyError, TypeError) as exc:
        raise PoisonMessage(f"unreadable message: {exc}") from exc

    if type_ == "ProductUpserted":
        try:
            product_id = data["product_id"]
            revision = int(data["revision"])
            if revision < 1:
                raise ValueError(f"revision must be at least 1, got {revision}")
            doc = document(data)
        except (KeyError, TypeError, ValueError) as exc:
            raise PoisonMessage(f"bad ProductUpserted payload: {exc!r}") from exc
        return write(es, index, product_id, revision, doc)

    if type_ == "ProductRemoved":
        try:
            product_id = data["product_id"]
        except (KeyError, TypeError) as exc:
            raise PoisonMessage(f"bad ProductRemoved payload: {exc!r}") from exc
        return remove(es, index, product_id)

    return "ignored"  # a type this service doesn't index

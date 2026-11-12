"""Queries against the product index: search with facets and sorting, and autosuggest."""

from elasticsearch import Elasticsearch

SEARCH_FIELDS = ["name^4", "brand^2", "category_names^1.5", "description"]

SORTS = {
    "relevance": [{"_score": "desc"}, {"product_id": "asc"}],
    "price_asc": [{"price_min": "asc"}, {"product_id": "asc"}],
    "price_desc": [{"price_min": "desc"}, {"product_id": "asc"}],
    "newest": [{"created_at": "desc"}, {"product_id": "asc"}],
}

# product_id as the last sort key keeps every page in the same order when scores or prices tie.
RESULT_FIELDS = [
    "product_id", "slug", "name", "brand", "category", "image_url",
    "price_min", "price_max", "colours", "sizes",
]

MAX_SUGGESTIONS = 8


def _money(value: float | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def build_query(q: str, min_price, max_price) -> dict:
    must = ([{"multi_match": {"query": q, "fields": SEARCH_FIELDS, "fuzziness": "AUTO"}}]
            if q else [{"match_all": {}}])
    filters = [{"term": {"listed": True}}]
    # A product matches a price range when its own range overlaps it.
    if min_price is not None:
        filters.append({"range": {"price_max": {"gte": float(min_price)}}})
    if max_price is not None:
        filters.append({"range": {"price_min": {"lte": float(max_price)}}})
    return {"bool": {"must": must, "filter": filters}}


def search_products(es: Elasticsearch, index: str, *, q: str, category: str | None, colour: str | None,
                    size: str | None, min_price, max_price, sort: str, page: int, page_size: int) -> dict:
    body: dict = {
        "query": build_query(q, min_price, max_price),
        # Facets count the matches before the chosen category, colour and size are applied,
        # so each facet still shows the other options for the search.
        "aggs": {
            "colours": {"terms": {"field": "colours", "size": 50}},
            "sizes": {"terms": {"field": "sizes", "size": 50}},
            "categories": {"terms": {"field": "category.slug", "size": 50},
                           "aggs": {"name": {"terms": {"field": "category.name", "size": 1}}}},
            "price_low": {"min": {"field": "price_min"}},
            "price_high": {"max": {"field": "price_max"}},
        },
    }
    filters = []
    if category:
        filters.append({"term": {"category_slugs": category}})  # includes products in its subcategories
    if colour:
        filters.append({"term": {"colours": colour}})
    if size:
        filters.append({"term": {"sizes": size}})
    if filters:
        body["post_filter"] = {"bool": {"filter": filters}}

    resp = es.search(index=index, sort=SORTS[sort], from_=(page - 1) * page_size, size=page_size,
                     track_total_hits=True, source_includes=RESULT_FIELDS, **body)
    hits, aggs = resp["hits"], resp["aggregations"]
    return {
        "total": hits["total"]["value"],
        "page": page,
        "page_size": page_size,
        "results": [hit["_source"] for hit in hits["hits"]],
        "facets": {
            "colours": [{"value": b["key"], "count": b["doc_count"]} for b in aggs["colours"]["buckets"]],
            "sizes": [{"value": b["key"], "count": b["doc_count"]} for b in aggs["sizes"]["buckets"]],
            "categories": [{
                "slug": b["key"],
                "name": b["name"]["buckets"][0]["key"] if b["name"]["buckets"] else b["key"],
                "count": b["doc_count"],
            } for b in aggs["categories"]["buckets"]],
            "price": {"min": _money(aggs["price_low"]["value"]), "max": _money(aggs["price_high"]["value"])},
        },
    }


def suggest_products(es: Elasticsearch, index: str, text: str) -> list[dict]:
    """Product names and brands that start with what the shopper has typed so far."""
    resp = es.search(index=index, size=0, source_includes=["slug"], suggest={"products": {
        "prefix": text,
        "completion": {"field": "suggest", "size": MAX_SUGGESTIONS, "skip_duplicates": True,
                       "fuzzy": {"fuzziness": 1}},
    }})
    options = resp["suggest"]["products"][0]["options"]
    return [{
        "text": option["text"],
        "product_id": option["_id"],
        "slug": option.get("_source", {}).get("slug"),
    } for option in options]

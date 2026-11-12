import pytest
from elasticsearch import Elasticsearch
from fastapi.testclient import TestClient

from app.main import app

SEARCH = "/api/v1/search/products"
SUGGEST = "/api/v1/search/suggest"


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def unreachable_es():
    """A client pointed at nothing: how the API behaves when Elasticsearch is down."""
    client = Elasticsearch("http://127.0.0.1:1", request_timeout=2, max_retries=0)
    yield client
    client.close()


def names(response):
    return [item["name"] for item in response.json()["results"]]


def test_health_is_ok_while_elasticsearch_is_up(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "search"}


def test_health_is_503_when_elasticsearch_is_down(client, monkeypatch, unreachable_es):
    monkeypatch.setattr(client.app.state, "es", unreachable_es)

    assert client.get("/health").status_code == 503


def test_search_is_503_when_elasticsearch_is_down(client, monkeypatch, unreachable_es):
    monkeypatch.setattr(client.app.state, "es", unreachable_es)

    assert client.get(SEARCH).status_code == 503
    assert client.get(SUGGEST, params={"q": "na"}).status_code == 503


def test_only_listed_products_are_returned(client, make_product, publish):
    publish(make_product("Navy Cotton Shirt"), make_product("Hidden Shirt", listed=False))

    body = client.get(SEARCH).json()

    assert body["total"] == 1
    assert names(client.get(SEARCH)) == ["Navy Cotton Shirt"]


def test_text_search_matches_name_and_brand(client, make_product, publish):
    publish(make_product("Navy Cotton Shirt", brand="Acme"),
            make_product("Leather Belt", brand="Northwind"))

    assert names(client.get(SEARCH, params={"q": "cotton"})) == ["Navy Cotton Shirt"]
    assert names(client.get(SEARCH, params={"q": "northwind"})) == ["Leather Belt"]


def test_filters_combine_for_category_colour_and_size(client, make_product, publish):
    publish(
        make_product("Navy Shirt", categories=(("clothing", "Clothing"), ("shirts", "Shirts")),
                     colours=("Navy",), sizes=("M",)),
        make_product("Red Jumper", categories=(("clothing", "Clothing"),), colours=("Red",), sizes=("L",)),
        make_product("Navy Trainer", categories=(("shoes", "Shoes"),), colours=("Navy",), sizes=("M",)),
    )

    def found(**params):
        return sorted(names(client.get(SEARCH, params=params)))

    assert found(category="clothing") == ["Navy Shirt", "Red Jumper"]  # includes subcategories
    assert found(colour="Navy") == ["Navy Shirt", "Navy Trainer"]
    assert found(size="M") == ["Navy Shirt", "Navy Trainer"]
    assert found(category="clothing", colour="Navy", size="M") == ["Navy Shirt"]


def test_price_range_matches_products_whose_range_overlaps_it(client, make_product, publish):
    publish(
        make_product("Cheap", price_min="10.00", price_max="20.00"),
        make_product("Dear", price_min="30.00", price_max="40.00"),
        make_product("Middling", price_min="15.00", price_max="35.00"),
    )

    found = names(client.get(SEARCH, params={"min_price": "21", "max_price": "29"}))

    assert found == ["Middling"]


def test_sorts_by_price_and_newest(client, make_product, publish):
    publish(
        make_product("Thirty", price_min="30.00", price_max="30.00", created_at="2026-11-01T10:00:00+00:00"),
        make_product("Ten", price_min="10.00", price_max="10.00", created_at="2026-11-03T10:00:00+00:00"),
        make_product("Twenty", price_min="20.00", price_max="20.00", created_at="2026-11-02T10:00:00+00:00"),
    )

    assert names(client.get(SEARCH, params={"sort": "price_asc"})) == ["Ten", "Twenty", "Thirty"]
    assert names(client.get(SEARCH, params={"sort": "price_desc"})) == ["Thirty", "Twenty", "Ten"]
    assert names(client.get(SEARCH, params={"sort": "newest"})) == ["Ten", "Twenty", "Thirty"]


def test_pages_cover_every_product_once(client, make_product, publish):
    publish(*[make_product(f"Item {n}") for n in range(5)])

    pages = [client.get(SEARCH, params={"page": p, "page_size": 2}).json() for p in (1, 2, 3)]
    seen = [item["product_id"] for page in pages for item in page["results"]]

    assert [len(page["results"]) for page in pages] == [2, 2, 1]
    assert pages[0]["total"] == 5
    assert len(set(seen)) == 5


def test_facets_count_the_matching_products(client, make_product, publish):
    publish(
        make_product("A", categories=(("clothing", "Clothing"), ("shirts", "Shirts")),
                     colours=("Navy", "Red"), sizes=("M",), price_min="10.00", price_max="20.00"),
        make_product("B", categories=(("clothing", "Clothing"),), colours=("Navy",), sizes=("L",),
                     price_min="30.00", price_max="40.00"),
        make_product("C", categories=(("shoes", "Shoes"),), colours=("Red",), sizes=("M",),
                     price_min="50.00", price_max="60.00"),
    )

    facets = client.get(SEARCH).json()["facets"]

    assert {f["value"]: f["count"] for f in facets["colours"]} == {"Navy": 2, "Red": 2}
    assert {f["value"]: f["count"] for f in facets["sizes"]} == {"M": 2, "L": 1}
    assert {f["slug"]: (f["name"], f["count"]) for f in facets["categories"]} == {
        "shirts": ("Shirts", 1), "clothing": ("Clothing", 1), "shoes": ("Shoes", 1)}
    assert facets["price"] == {"min": "10.00", "max": "60.00"}


def test_rejects_an_inverted_price_range_and_a_big_page(client):
    assert client.get(SEARCH, params={"min_price": "50", "max_price": "10"}).status_code == 400
    assert client.get(SEARCH, params={"page_size": 100}).status_code == 422


def test_suggest_offers_listed_names_only(client, make_product, publish):
    publish(make_product("Navy Cotton Shirt"), make_product("Navy Hidden", listed=False))

    results = client.get(SUGGEST, params={"q": "nav"}).json()["results"]

    assert [r["text"] for r in results] == ["Navy Cotton Shirt"]
    assert results[0]["slug"] == "navy-cotton-shirt"


def test_suggest_is_empty_for_a_blank_query(client):
    assert client.get(SUGGEST, params={"q": "   "}).json() == {"results": []}

"""Pages, scripts and images are passed to the storefront."""

import httpx

from .conftest import auth


def test_pages_go_to_the_storefront_unchanged(gateway, services):
    response = gateway.get("/products", params={"category": "phones", "sort": "price"})

    assert response.status_code == 200
    assert services.last.url.host == "storefront"
    assert services.last.url.path == "/products"
    assert services.last.url.query == b"category=phones&sort=price"


def test_the_home_page_and_build_files_go_to_the_storefront(gateway, services):
    gateway.get("/")
    assert (services.last.url.host, services.last.url.path) == ("storefront", "/")
    gateway.get("/_next/static/chunks/main-abc123.js")
    assert services.last.url.path == "/_next/static/chunks/main-abc123.js"


def test_pages_are_not_rate_limited_or_token_checked(make_gateway, services):
    gateway = make_gateway(rate_limit_default="1/minute")

    for _ in range(3):
        response = gateway.get("/orders", headers=auth("stale-token"))
        assert response.status_code == 200
        assert "ratelimit-limit" not in response.headers


def test_pages_get_the_visitors_address_and_a_request_id(gateway, services):
    response = gateway.get("/cart", headers={"X-Forwarded-For": "6.6.6.6"})

    assert services.last.headers["x-forwarded-for"] == "testclient"
    assert services.last.headers["x-request-id"] == response.headers["x-request-id"]


def test_page_redirects_and_html_are_passed_back(gateway, services):
    services.answer = lambda r: httpx.Response(307, headers={"Location": "/admin/orders"})

    response = gateway.get("/admin", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/admin/orders"


def test_the_gateways_own_health_is_not_sent_to_the_storefront(gateway, services):
    assert gateway.get("/health").json()["service"] == "gateway"
    assert services.received == []


def test_a_storefront_that_is_down_gives_502(gateway, services):
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    services.answer = refuse

    response = gateway.get("/products")

    assert response.status_code == 502
    assert response.json()["detail"] == "The storefront service could not be reached."

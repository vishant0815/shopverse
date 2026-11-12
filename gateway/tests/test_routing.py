import gzip
import json

import httpx
import pytest

from .conftest import body_of


@pytest.mark.parametrize("path, service", [
    ("/api/v1/auth/login/", "users"),
    ("/api/v1/users/me/", "users"),
    ("/api/v1/addresses/", "users"),
    ("/api/v1/categories/tree/", "products"),
    ("/api/v1/products/", "products"),
    ("/api/v1/variants/lookup/", "products"),
    ("/api/v1/seller/products/", "products"),
    ("/api/v1/cart/", "orders"),
    ("/api/v1/checkout/", "orders"),
    ("/api/v1/orders/SV-1/", "orders"),
    ("/api/v1/seller/sales/", "orders"),
    ("/api/v1/seller/summary/", "orders"),
    ("/api/v1/admin/orders/", "orders"),
    ("/api/v1/payments", "payments"),
    ("/api/v1/payments/SV-1", "payments"),
    ("/api/v1/webhooks/stripe", "payments"),
    ("/api/v1/inventory/availability", "inventory"),
    ("/api/v1/inventory/stock/", "inventory"),
])
def test_each_path_goes_to_its_service_unchanged(gateway, services, path, service):
    response = gateway.get(path, params={"page": "2", "search": "desk lamp"})

    assert response.status_code == 200
    assert services.last.url.host == service
    assert services.last.url.path == path
    assert response.json()["query"] == "page=2&search=desk+lamp"


def test_longest_prefix_wins(gateway, services):
    gateway.get("/api/v1/seller/products/abc/")
    assert services.last.url.host == "products"
    gateway.get("/api/v1/seller/sales/")
    assert services.last.url.host == "orders"


def test_payments_health_is_rewritten(gateway, services):
    gateway.get("/api/payments-health")
    assert services.last.url.host == "payments"
    assert services.last.url.path == "/health"


@pytest.mark.parametrize("path", [
    "/api/v1/nothing-here/",
    "/api/v1/internal/orders/SV-1/payment-confirmed/",  # service-to-service only
    "/api/payments-health/extra",
    "/api/v2/products/",
])
def test_unknown_and_internal_paths_never_reach_a_service(gateway, services, path):
    response = gateway.post(path, json={})

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
    assert services.received == []


def test_method_body_and_headers_are_forwarded(gateway, services):
    response = gateway.patch(
        "/api/v1/cart/items/abc/",
        json={"quantity": 3},
        headers={"Accept-Language": "en-GB", "Idempotency-Key": "k-123", "Upgrade": "websocket",
                 "Keep-Alive": "timeout=5", "TE": "trailers"},
    )

    assert response.status_code == 200
    sent = services.last
    assert sent.method == "PATCH"
    assert body_of(sent) == {"quantity": 3}
    assert sent.headers["accept-language"] == "en-GB"
    assert sent.headers["idempotency-key"] == "k-123"
    assert sent.headers["host"] == "orders:8000"
    for hop_by_hop in ("upgrade", "keep-alive", "te"):
        assert hop_by_hop not in sent.headers


def test_no_headers_are_added_that_the_caller_did_not_send(gateway, services):
    for name in ("accept", "accept-encoding", "user-agent"):
        del gateway.headers[name]

    gateway.get("/api/v1/products/")

    for name in ("accept", "accept-encoding", "user-agent"):
        assert name not in services.last.headers


def test_service_answers_are_passed_back_as_they_are(gateway, services):
    services.answer = lambda r: httpx.Response(
        409, json={"detail": "Out of stock"},
        headers=[("Set-Cookie", "a=1; Path=/"), ("Set-Cookie", "b=2; Path=/"), ("X-Custom", "yes")],
    )

    response = gateway.post("/api/v1/checkout/", json={})

    assert response.status_code == 409
    assert response.json() == {"detail": "Out of stock"}
    assert response.headers.get_list("set-cookie") == ["a=1; Path=/", "b=2; Path=/"]
    assert response.headers["x-custom"] == "yes"


def test_one_visitors_cookies_are_never_given_to_another(gateway, services):
    # Visitor A signs in and the users service sets their refresh cookie.
    services.answer = lambda r: httpx.Response(200, json={}, headers={"Set-Cookie": "refresh_token=alices; Path=/"})
    signed_in = gateway.post("/api/v1/auth/login/", json={})
    assert signed_in.headers["set-cookie"] == "refresh_token=alices; Path=/"

    # Visitor B (no cookies of their own) must not be sent A's.
    services.answer = None
    gateway.cookies.clear()
    gateway.post("/api/v1/auth/refresh/")

    assert "cookie" not in services.last.headers


def test_a_visitors_own_cookies_are_passed_on_as_sent(gateway, services):
    gateway.post("/api/v1/auth/refresh/", headers={"Cookie": "refresh_token=bobs"})

    assert services.last.headers["cookie"] == "refresh_token=bobs"


def test_redirects_are_passed_back_not_followed(gateway, services):
    services.answer = lambda r: httpx.Response(301, headers={"Location": "/api/v1/cart/"})

    response = gateway.get("/api/v1/cart", follow_redirects=False)

    assert response.status_code == 301
    assert response.headers["location"] == "/api/v1/cart/"
    assert len(services.received) == 1


def test_compressed_answers_stay_intact(gateway, services):
    payload = json.dumps({"results": ["lamp"] * 200}).encode()
    services.answer = lambda r: httpx.Response(
        200, content=gzip.compress(payload),
        headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
    )

    response = gateway.get("/api/v1/products/")

    assert response.headers["content-encoding"] == "gzip"
    assert response.json() == json.loads(payload)


def test_request_id_is_made_echoed_and_forwarded(gateway, services):
    response = gateway.get("/api/v1/products/")

    request_id = response.headers["x-request-id"]
    assert len(request_id) == 32
    assert services.last.headers["x-request-id"] == request_id


def test_a_sane_request_id_from_the_caller_is_kept(gateway, services):
    response = gateway.get("/api/v1/products/", headers={"X-Request-ID": "trace-abc-123"})

    assert response.headers["x-request-id"] == "trace-abc-123"
    assert services.last.headers["x-request-id"] == "trace-abc-123"


def test_a_junk_request_id_is_replaced(gateway, services):
    response = gateway.get("/api/v1/products/", headers={"X-Request-ID": "<script>"})

    assert response.headers["x-request-id"] != "<script>"
    assert services.last.headers["x-request-id"] == response.headers["x-request-id"]


def test_errors_made_by_the_gateway_carry_the_request_id(gateway):
    response = gateway.get("/api/v1/nope/", headers={"X-Request-ID": "trace-404-test"})
    assert response.headers["x-request-id"] == "trace-404-test"


def test_as_the_edge_the_socket_address_is_used_and_claims_are_ignored(gateway, services):
    gateway.get("/api/v1/products/", headers={"X-Forwarded-For": "6.6.6.6"})

    # A one-entry header with the real caller (the test client's socket), not 6.6.6.6.
    assert services.last.headers["x-forwarded-for"] == "testclient"


def test_behind_a_load_balancer_its_entry_is_used_not_the_clients(make_gateway, services):
    gateway = make_gateway(trusted_proxy_hops=1)

    # The client claims to be 6.6.6.6; the load balancer appended the address it really saw.
    gateway.get("/api/v1/products/", headers={"X-Forwarded-For": "6.6.6.6, 203.0.113.9"})

    assert services.last.headers["x-forwarded-for"] == "203.0.113.9"


def test_a_garbage_forwarded_address_is_ignored(make_gateway, services):
    gateway = make_gateway(trusted_proxy_hops=1)
    gateway.get("/api/v1/products/", headers={"X-Forwarded-For": "not-an-ip"})
    assert services.last.headers["x-forwarded-for"] == "testclient"


def test_forwarded_proto_and_host_from_a_load_balancer_are_passed_on(make_gateway, services):
    gateway = make_gateway(trusted_proxy_hops=1)
    gateway.get("/api/v1/products/", headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "shop.example"})

    assert services.last.headers["x-forwarded-proto"] == "https"
    assert services.last.headers["x-forwarded-host"] == "shop.example"


def test_as_the_edge_forwarded_proto_and_host_from_clients_are_ignored(gateway, services):
    gateway.get("/api/v1/products/", headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "evil.example"})

    assert services.last.headers["x-forwarded-proto"] == "http"
    assert services.last.headers["x-forwarded-host"] == "testserver"


def test_oversized_bodies_are_refused_before_forwarding(make_gateway, services):
    gateway = make_gateway(max_body_bytes=100)

    response = gateway.post("/api/v1/products/", content=b"x" * 101)

    assert response.status_code == 413
    assert services.received == []


def test_a_body_at_the_limit_is_fine(make_gateway, services):
    gateway = make_gateway(max_body_bytes=100)

    response = gateway.post("/api/v1/products/", content=b"x" * 100)

    assert response.status_code == 200
    assert services.last.content == b"x" * 100

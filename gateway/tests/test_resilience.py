import httpx

from app.breaker import Breaker


def refuse(request):
    raise httpx.ConnectError("connection refused", request=request)


def hang(request):
    raise httpx.ReadTimeout("timed out", request=request)


def test_a_service_that_is_down_gives_502(gateway, services):
    services.answer = refuse

    response = gateway.post("/api/v1/checkout/", json={})

    assert response.status_code == 502
    assert response.json() == {"detail": "The orders service could not be reached.", "code": "bad_gateway"}


def test_a_slow_service_gives_504(gateway, services):
    services.answer = hang

    response = gateway.get("/api/v1/products/")

    assert response.status_code == 504
    assert response.json()["code"] == "gateway_timeout"


def test_a_500_from_a_service_is_passed_on_not_counted_as_down(make_gateway, services):
    gateway = make_gateway(breaker_failure_threshold=1)
    services.answer = lambda r: httpx.Response(500, json={"detail": "boom"})

    assert gateway.get("/api/v1/products/").status_code == 500
    assert gateway.get("/api/v1/products/").status_code == 500
    assert len(services.received) == 2


def test_reads_are_retried_once_when_the_connection_fails(gateway, services):
    calls = []

    def flaky(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={"ok": True})

    services.answer = flaky

    response = gateway.get("/api/v1/products/")

    assert response.status_code == 200
    assert len(calls) == 2


def test_writes_are_never_retried(gateway, services):
    services.answer = refuse

    response = gateway.post("/api/v1/checkout/", json={})

    assert response.status_code == 502
    assert len(services.received) == 1


def test_the_breaker_opens_after_repeated_failures_and_recovers(make_gateway, services, clock):
    gateway = make_gateway(breaker_failure_threshold=3, breaker_reset_seconds=10)
    services.answer = refuse
    for _ in range(3):
        assert gateway.post("/api/v1/checkout/", json={}).status_code == 502
    reached = len(services.received)

    # Open: answered straight away, the service isn't bothered.
    blocked = gateway.post("/api/v1/checkout/", json={})
    assert blocked.status_code == 503
    assert blocked.json()["code"] == "service_unavailable"
    assert blocked.headers["retry-after"] == "10"
    assert len(services.received) == reached

    # Other services are unaffected.
    assert gateway.post("/api/v1/auth/login/", json={}).status_code == 502
    services.answer = None
    assert gateway.get("/api/v1/products/").status_code == 200

    # After the cool-down one trial goes through; it works, so the breaker closes.
    clock.now += 10
    assert gateway.post("/api/v1/checkout/", json={}).status_code == 200
    assert gateway.post("/api/v1/checkout/", json={}).status_code == 200


def test_a_failed_trial_opens_the_breaker_again(make_gateway, services, clock):
    gateway = make_gateway(breaker_failure_threshold=2, breaker_reset_seconds=10)
    services.answer = refuse
    for _ in range(2):
        gateway.post("/api/v1/checkout/", json={})

    clock.now += 10
    assert gateway.post("/api/v1/checkout/", json={}).status_code == 502
    assert gateway.post("/api/v1/checkout/", json={}).status_code == 503


def test_only_one_trial_request_while_half_open():
    now = [0.0]
    breaker = Breaker(threshold=1, reset_seconds=5, clock=lambda: now[0])
    breaker.failure()
    assert breaker.state == "open"
    assert not breaker.allow()

    now[0] = 5
    assert breaker.state == "half_open"
    assert breaker.allow()
    assert not breaker.allow()

    breaker.success()
    assert breaker.state == "closed"
    assert breaker.allow()


def test_health_says_the_gateway_is_up(gateway, services):
    response = gateway.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "gateway"}
    assert services.received == []


def test_readiness_checks_redis_and_every_service(gateway, services):
    response = gateway.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["checks"] == {"redis": "ok", "users": "ok", "products": "ok", "orders": "ok",
                                         "payments": "ok", "inventory": "ok", "search": "ok", "storefront": "ok"}
    asked = {(r.url.host, r.url.path) for r in services.received}
    assert asked == {("users", "/health/"), ("products", "/health/"), ("orders", "/health/"),
                     ("payments", "/health"), ("inventory", "/health"), ("search", "/health"),
                     ("storefront", "/favicon.svg")}


def test_readiness_reports_a_service_that_is_down(gateway, services):
    services.answer = lambda r: refuse(r) if r.url.host == "orders" else httpx.Response(200, json={})

    response = gateway.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["orders"] == "unreachable"
    assert response.json()["checks"]["users"] == "ok"

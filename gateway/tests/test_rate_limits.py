import asyncio
import time

import pytest
from redis.asyncio import Redis

from app.config import Settings
from app.ratelimit import Policies, Policy, Rate, RateLimiter

from .conftest import BASE_SETTINGS, TEST_REDIS_URL, auth, make_token


def ip(address):
    """Headers as a load balancer in front of the gateway would send them for this caller."""
    return {"X-Forwarded-For": address}


@pytest.fixture
def limited_gateway(make_gateway):
    """A gateway behind one load balancer, so tests can play callers at different addresses."""
    return lambda **settings: make_gateway(trusted_proxy_hops=1, **settings)


def test_requests_carry_rate_limit_headers(limited_gateway):
    gateway = limited_gateway(rate_limit_default="5/minute")

    first = gateway.get("/api/v1/products/", headers=ip("198.51.100.1"))
    second = gateway.get("/api/v1/products/", headers=ip("198.51.100.1"))

    assert first.headers["ratelimit-limit"] == "5"
    assert first.headers["ratelimit-remaining"] == "4"
    assert second.headers["ratelimit-remaining"] == "3"
    assert int(second.headers["ratelimit-reset"]) > 0


def test_over_the_limit_is_429_and_never_reaches_the_service(limited_gateway, services):
    gateway = limited_gateway(rate_limit_default="3/minute")
    for _ in range(3):
        assert gateway.get("/api/v1/products/", headers=ip("198.51.100.1")).status_code == 200

    response = gateway.get("/api/v1/products/", headers=ip("198.51.100.1"))

    assert response.status_code == 429
    assert response.json()["code"] == "rate_limited"
    assert response.json()["detail"] == "Too many requests. Try again in 20 seconds."
    assert response.headers["retry-after"] == "20"
    assert response.headers["ratelimit-remaining"] == "0"
    assert len(services.received) == 3


def test_anonymous_callers_are_counted_by_address(limited_gateway):
    gateway = limited_gateway(rate_limit_default="1/minute")

    assert gateway.get("/api/v1/products/", headers=ip("198.51.100.1")).status_code == 200
    assert gateway.get("/api/v1/products/", headers=ip("198.51.100.2")).status_code == 200
    assert gateway.get("/api/v1/products/", headers=ip("198.51.100.1")).status_code == 429


def test_signed_in_users_are_counted_by_user_not_address(limited_gateway):
    gateway = limited_gateway(rate_limit_default="1/minute")
    alice, bob = make_token(), make_token()
    shared_office_ip = ip("198.51.100.7")

    assert gateway.get("/api/v1/orders/", headers={**auth(alice), **shared_office_ip}).status_code == 200
    assert gateway.get("/api/v1/orders/", headers={**auth(bob), **shared_office_ip}).status_code == 200
    assert gateway.get("/api/v1/orders/", headers={**auth(alice), **ip("198.51.100.8")}).status_code == 429


def test_sign_in_attempts_have_their_own_tighter_limit_per_address(limited_gateway):
    gateway = limited_gateway(rate_limit_login="2/minute", rate_limit_default="100/minute")
    for _ in range(2):
        assert gateway.post("/api/v1/auth/login/", json={}, headers=ip("198.51.100.1")).status_code == 200

    blocked = gateway.post("/api/v1/auth/register/", json={}, headers=ip("198.51.100.1"))

    assert blocked.status_code == 429
    assert blocked.headers["ratelimit-limit"] == "2"
    # Browsing isn't affected, and another address can still sign in.
    assert gateway.get("/api/v1/products/", headers=ip("198.51.100.1")).status_code == 200
    assert gateway.post("/api/v1/auth/login/", json={}, headers=ip("198.51.100.2")).status_code == 200


def test_token_refresh_does_not_use_up_sign_in_attempts(limited_gateway):
    gateway = limited_gateway(rate_limit_login="1/minute", rate_limit_refresh="3/minute")
    gateway.post("/api/v1/auth/login/", json={}, headers=ip("198.51.100.1"))

    for _ in range(3):
        assert gateway.post("/api/v1/auth/refresh/", headers=ip("198.51.100.1")).status_code == 200
    assert gateway.post("/api/v1/auth/refresh/", headers=ip("198.51.100.1")).status_code == 429


def test_placing_and_paying_for_orders_has_its_own_limit_per_user(limited_gateway):
    gateway = limited_gateway(rate_limit_checkout="2/minute", rate_limit_default="100/minute")
    headers = auth(make_token())

    assert gateway.post("/api/v1/checkout/", json={}, headers=headers).status_code == 200
    assert gateway.post("/api/v1/payments", json={}, headers=headers).status_code == 200
    assert gateway.post("/api/v1/payments/SV-1/simulate", json={}, headers=headers).status_code == 429
    # Looking at orders is still fine.
    assert gateway.get("/api/v1/orders/", headers=headers).status_code == 200


def test_stripe_webhooks_are_not_rate_limited(limited_gateway):
    gateway = limited_gateway(rate_limit_default="1/minute")

    for _ in range(3):
        response = gateway.post("/api/v1/webhooks/stripe", content=b"{}")
        assert response.status_code == 200
        assert "ratelimit-limit" not in response.headers


def test_guessing_tokens_is_rate_limited_too(limited_gateway, services):
    gateway = limited_gateway(rate_limit_default="2/minute")
    for _ in range(2):
        assert gateway.get("/api/v1/orders/", headers={**auth("bad"), **ip("198.51.100.1")}).status_code == 401

    response = gateway.get("/api/v1/orders/", headers={**auth("bad"), **ip("198.51.100.1")})

    assert response.status_code == 429
    assert services.received == []


def test_the_bucket_refills_over_time(limited_gateway):
    gateway = limited_gateway(rate_limit_default="2/second")
    gateway.get("/api/v1/products/")
    gateway.get("/api/v1/products/")
    assert gateway.get("/api/v1/products/").status_code == 429

    time.sleep(0.6)

    assert gateway.get("/api/v1/products/").status_code == 200


def test_when_redis_is_down_requests_still_go_through(limited_gateway, services):
    gateway = limited_gateway(redis_url="redis://127.0.0.1:1/0", rate_limit_default="1/minute")

    for _ in range(3):
        response = gateway.get("/api/v1/products/")
        assert response.status_code == 200
        assert "ratelimit-limit" not in response.headers
    assert len(services.received) == 3


def test_rate_limiting_can_be_switched_off(limited_gateway):
    gateway = limited_gateway(rate_limit_enabled=False, rate_limit_default="1/minute")

    for _ in range(3):
        response = gateway.get("/api/v1/products/")
        assert response.status_code == 200
        assert "ratelimit-limit" not in response.headers


def test_concurrent_requests_cannot_overspend_the_bucket():
    """Fifty requests at once against a bucket of 10: exactly 10 get in."""

    async def run():
        redis = Redis.from_url(TEST_REDIS_URL)
        limiter = RateLimiter(redis)
        policy = Policy("race", Rate(10, 3600), "ip")
        decisions = await asyncio.gather(*(limiter.hit(policy, "ip:198.51.100.1") for _ in range(50)))
        await redis.aclose()
        return decisions

    decisions = asyncio.run(run())

    assert sum(d.allowed for d in decisions) == 10


@pytest.mark.parametrize("text, expected", [
    ("10/minute", Rate(10, 60)),
    ("1/second", Rate(1, 1)),
    (" 500 / hour ", Rate(500, 3600)),
])
def test_rates_are_read_from_settings(text, expected):
    assert Rate.parse(text) == expected


@pytest.mark.parametrize("text", ["10", "0/minute", "ten/minute", "10/day", "-1/second"])
def test_badly_written_rates_stop_the_gateway_starting(text):
    with pytest.raises(ValueError):
        Policies(Settings(**{**BASE_SETTINGS, "rate_limit_default": text}))

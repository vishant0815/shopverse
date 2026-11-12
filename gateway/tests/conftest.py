import json
import os
import time
import uuid

# Configure before the app is imported (settings are read once).
os.environ["JWT_SIGNING_KEY"] = "test-signing-key-that-is-long-enough-for-hs256"
# Same Redis server as configured (inside Docker that's the "redis" container), but
# database 15, which the tests empty before and after each test. Never the real one.
_configured = os.environ.get("REDIS_URL", "redis://localhost:6379/2")
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", _configured.rsplit("/", 1)[0] + "/15")
os.environ["REDIS_URL"] = TEST_REDIS_URL

import httpx  # noqa: E402
import jwt  # noqa: E402
import pytest  # noqa: E402
import redis  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

SIGNING_KEY = os.environ["JWT_SIGNING_KEY"]

BASE_SETTINGS = {
    "jwt_signing_key": SIGNING_KEY,
    "redis_url": TEST_REDIS_URL,
    "users_service_url": "http://users:8000",
    "products_service_url": "http://products:8000",
    "orders_service_url": "http://orders:8000",
    "payments_service_url": "http://payments:8000",
    "inventory_service_url": "http://inventory:8000",
    "storefront_url": "http://storefront:3000",
    "trusted_proxy_hops": 0,
}


class LiveStream(httpx.AsyncByteStream):
    """A body that arrives as a stream, like it does from a real socket.

    httpx reads `Response(content=...)` bodies straight away, which a real service
    response never is; the gateway streams answers back, so tests must too.
    """

    def __init__(self, data: bytes):
        self.data = data

    async def __aiter__(self):
        yield self.data


def as_live(response: httpx.Response) -> httpx.Response:
    raw = b"".join(response.stream)  # the bytes as sent, still compressed if they were
    return httpx.Response(response.status_code, headers=response.headers, stream=LiveStream(raw))


class FakeServices:
    """Stands in for the four services. Records what reached them; answers 200 by default.

    Set `answer` to a function (request) -> httpx.Response, or raise from it to simulate
    a service that is down or slow.
    """

    def __init__(self):
        self.received: list[httpx.Request] = []
        self.answer = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.received.append(request)
        if self.answer:
            return as_live(self.answer(request))
        return as_live(httpx.Response(200, json={"service": request.url.host, "path": request.url.path,
                                                 "query": request.url.query.decode()}))

    @property
    def last(self) -> httpx.Request:
        return self.received[-1]


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def clean_redis():
    client = redis.Redis.from_url(TEST_REDIS_URL)
    client.flushdb()
    yield
    client.flushdb()
    client.close()


@pytest.fixture
def services():
    return FakeServices()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def make_gateway(services, clock):
    """make_gateway(**settings) -> a started TestClient for a gateway with those settings."""
    opened = []

    def make(**overrides):
        settings = Settings(**{**BASE_SETTINGS, **overrides})
        client = TestClient(create_app(settings, transport=httpx.MockTransport(services), clock=clock))
        client.__enter__()
        opened.append(client)
        return client

    yield make
    for client in opened:
        client.__exit__(None, None, None)


@pytest.fixture
def gateway(make_gateway):
    return make_gateway()


def make_token(user_id=None, role="customer", token_type="access", expires_in=300, key=SIGNING_KEY, algorithm="HS256"):
    now = int(time.time())
    claims = {"token_type": token_type, "user_id": str(user_id or uuid.uuid4()), "role": role,
              "iat": now, "exp": now + expires_in, "jti": uuid.uuid4().hex}
    return jwt.encode(claims, key, algorithm=algorithm)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def body_of(request: httpx.Request):
    return json.loads(request.content) if request.content else None

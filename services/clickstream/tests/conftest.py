import os
import uuid
from datetime import datetime, timedelta, timezone

# Set before the app is imported: its settings are read when the module loads.
os.environ.setdefault("JWT_SIGNING_KEY", "test-only-jwt-signing-key-0123456789abcdef")
os.environ.setdefault("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

import jwt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.messaging import QueueFull  # noqa: E402
from app.routes import get_publisher  # noqa: E402

KEY = os.environ["JWT_SIGNING_KEY"]


class FakePublisher:
    def __init__(self):
        self.sent: list[tuple[str, dict]] = []
        self.full = False

    def send(self, key: str, payload: dict) -> None:
        if self.full:
            raise QueueFull()
        self.sent.append((key, payload))

    def close(self) -> None:
        pass


@pytest.fixture
def publisher():
    fake = FakePublisher()
    app.dependency_overrides[get_publisher] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    # Not used as a context manager, so the lifespan (which talks to Kafka) does not run.
    return TestClient(app)


def access_token(user_id: uuid.UUID, *, expires_in: int = 900, token_type: str = "access") -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "user_id": str(user_id),
            "role": "customer",
            "token_type": token_type,
            "iat": now,
            "exp": now + timedelta(seconds=expires_in),
        },
        KEY,
        algorithm="HS256",
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def product_view(**overrides) -> dict:
    event = {
        "event_id": str(uuid.uuid4()),
        "type": "product_view",
        "occurred_at": now_iso(),
        "session_id": "anon-session-1",
        "product_id": str(uuid.uuid4()),
        "source": "search",
    }
    return event | overrides

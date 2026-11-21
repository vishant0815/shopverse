import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import psycopg
import pytest

# Tests run against a database that gets emptied, so it must be named on purpose.
TEST_DATABASE_URL = os.environ.get("ANALYTICS_TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    raise pytest.UsageError("Set ANALYTICS_TEST_DATABASE_URL to a database that can be emptied (see README.md).")

# Set before the app is imported: its settings are read when the module loads.
KEY = "test-only-jwt-signing-key-0123456789abcdef"
os.environ["JWT_SIGNING_KEY"] = KEY
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

# The schema is shared with the Spark job, so the tests read the same file.
SCHEMA = Path(__file__).resolve().parents[3] / "infra" / "postgres" / "analytics" / "schema.sql"


@pytest.fixture
def db() -> str:
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute(SCHEMA.read_text(encoding="utf-8"))
        conn.execute("TRUNCATE product_listings, product_daily")
    return TEST_DATABASE_URL


@pytest.fixture
def client(db):
    return TestClient(app)


def today():
    return datetime.now(timezone.utc).date()


def token(user_id: uuid.UUID, *, role: str = "seller", token_type: str = "access", expires_in: int = 900) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "user_id": str(user_id),
            "role": role,
            "token_type": token_type,
            "iat": now,
            "exp": now + timedelta(seconds=expires_in),
        },
        KEY,
        algorithm="HS256",
    )


def auth(user_id: uuid.UUID, **kwargs) -> dict:
    return {"Authorization": f"Bearer {token(user_id, **kwargs)}"}


def seed_product(conn, seller: uuid.UUID, name: str) -> uuid.UUID:
    product = uuid.uuid4()
    conn.execute(
        "INSERT INTO product_listings (product_id, seller_id, name, slug, image_url, revision)"
        " VALUES (%s, %s, %s, %s, '', 1)",
        (product, seller, name, name.lower().replace(" ", "-")),
    )
    return product


def seed_day(conn, product: uuid.UUID, day, views: int, carts: int, sold: int) -> None:
    conn.execute(
        "INSERT INTO product_daily (product_id, day, views, add_to_carts, units_sold)"
        " VALUES (%s, %s, %s, %s, %s)",
        (product, day, views, carts, sold),
    )

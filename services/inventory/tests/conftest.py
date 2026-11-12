import os
import time
import uuid

# Configure before the app is imported (settings are read once).
# Tests always use their own database and never touch inventory_db, even inside the container.
os.environ["DB_NAME"] = os.environ.get("TEST_DB_NAME", "inventory_test")
os.environ.setdefault("DB_USER", "shopverse")
os.environ.setdefault("DB_PASSWORD", "shopverse")
os.environ["JWT_SIGNING_KEY"] = "test-signing-key-that-is-long-enough-for-hs256"
os.environ["DEMO_STOCK"] = "false"

import jwt  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select, text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import get_engine, get_sessionmaker  # noqa: E402
from app.main import app  # noqa: E402
from app.messaging import OutboxMessage, process  # noqa: E402
from app.models import StockItem  # noqa: E402
from app.stock import HANDLERS  # noqa: E402

SIGNING_KEY = os.environ["JWT_SIGNING_KEY"]
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session", autouse=True)
def database():
    """Build the test database with the real migrations, so they're tested too."""
    settings = get_settings()
    admin_url = settings.database_url.rsplit("/", 1)[0] + "/postgres"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": settings.db_name})
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{settings.db_name}"'))
    admin.dispose()

    config = Config(os.path.join(HERE, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(HERE, "migrations"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield


@pytest.fixture(autouse=True)
def clean_tables():
    yield
    with get_engine().begin() as conn:
        conn.execute(text("TRUNCATE stock_items, reservations, reservation_lines, outbox, processed_messages"))


@pytest.fixture
def sessions():
    return get_sessionmaker()


def envelope(type_, data, key=None, message_id=None):
    return {
        "id": str(message_id or uuid.uuid4()),
        "type": type_,
        "source": "test",
        "occurred_at": "2026-11-12T10:00:00.000Z",
        "key": key or data.get("order_number") or data.get("variant_id"),
        "data": data,
    }


@pytest.fixture
def send(sessions):
    """send(type, data) runs a message through the real handler path (dedupe and all)."""
    import json

    def send(type_, data, topic="inventory.commands", message_id=None):
        raw = json.dumps(envelope(type_, data, message_id=message_id)).encode()
        return process(sessions, HANDLERS, topic, raw)

    return send


@pytest.fixture
def add_stock(sessions):
    def add_stock(on_hand, reserved=0, seller_id=None, active=True, sku="SKU-1"):
        item = StockItem(variant_id=uuid.uuid4(), product_id=uuid.uuid4(), seller_id=seller_id or uuid.uuid4(),
                         sku=sku, on_hand=on_hand, reserved=reserved, active=active)
        with sessions() as db:
            db.add(item)
            db.commit()
        return item.variant_id

    return add_stock


@pytest.fixture
def stock(sessions):
    def stock(variant_id):
        with sessions() as db:
            item = db.get(StockItem, variant_id)
            return (item.on_hand, item.reserved)

    return stock


@pytest.fixture
def outbox(sessions):
    """outbox() -> the messages written so far, oldest first, as (type, data)."""
    def outbox():
        with sessions() as db:
            rows = db.scalars(select(OutboxMessage).order_by(OutboxMessage.seq)).all()
            return [(row.type, row.payload["data"]) for row in rows]

    return outbox


def make_token(user_id=None, role="seller", token_type="access", expires_in=300):
    now = int(time.time())
    claims = {"token_type": token_type, "user_id": str(user_id or uuid.uuid4()), "role": role,
              "iat": now, "exp": now + expires_in, "jti": uuid.uuid4().hex}
    return jwt.encode(claims, SIGNING_KEY, algorithm="HS256")


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def as_user(user_id=None, role="seller"):
    return {"Authorization": f"Bearer {make_token(user_id, role)}"}

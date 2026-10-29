import os
import time
import uuid
from decimal import Decimal

# Configure before the app is imported (settings are read once).
# Tests always use their own database and never touch payments_db, even inside the container.
os.environ["DB_NAME"] = os.environ.get("TEST_DB_NAME", "payments_test")
os.environ.setdefault("DB_USER", "shopverse")
os.environ.setdefault("DB_PASSWORD", "shopverse")
os.environ["JWT_SIGNING_KEY"] = "test-signing-key-that-is-long-enough-for-hs256"
os.environ["PAYMENT_PROVIDER"] = "fake"

import jwt  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app import orders_client  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import get_engine  # noqa: E402
from app.main import app  # noqa: E402

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
        conn.execute(text("TRUNCATE payments, processed_events"))


def make_token(user_id=None, role="customer", token_type="access", expires_in=300, key=SIGNING_KEY, algorithm="HS256"):
    now = int(time.time())
    claims = {"token_type": token_type, "user_id": str(user_id or uuid.uuid4()), "role": role,
              "iat": now, "exp": now + expires_in, "jti": uuid.uuid4().hex}
    return jwt.encode(claims, key, algorithm=algorithm)


class Customer:
    def __init__(self, client):
        self.id = uuid.uuid4()
        self.token = make_token(self.id)
        self.client = client

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def post(self, url, **kwargs):
        return self.client.post(url, headers=self.headers, **kwargs)

    def get(self, url, **kwargs):
        return self.client.get(url, headers=self.headers, **kwargs)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def customer(client):
    return Customer(client)


@pytest.fixture
def other_customer(client):
    return Customer(client)


class FakeOrders:
    """Stands in for the orders service."""

    def __init__(self):
        self.orders = {}        # number -> {"owner", "status", "total", "currency"}
        self.confirmed = []     # (number, payment_id, amount, currency)
        self.down = False

    def add(self, owner, total="59.98", status="pending_payment", currency="GBP"):
        number = f"SV-20261029-{uuid.uuid4().hex[:6].upper()}"
        self.orders[number] = {"owner": owner, "status": status, "total": Decimal(total), "currency": currency}
        return number

    def get_order(self, number, customer_token):
        if self.down:
            raise orders_client.OrdersUnavailable
        order = self.orders.get(number)
        caller = uuid.UUID(jwt.decode(customer_token, SIGNING_KEY, algorithms=["HS256"])["user_id"])
        if order is None or order["owner"] != caller:
            raise orders_client.OrderNotFound
        return orders_client.OrderInfo(number=number, status=order["status"], total=order["total"],
                                       currency=order["currency"])

    def confirm_payment(self, number, payment_id, amount, currency):
        if self.down:
            raise orders_client.OrdersUnavailable
        order = self.orders[number]
        if amount != order["total"]:
            return orders_client.ConfirmResult(ok=False, code="amount_mismatch")
        if order["status"] == "cancelled":
            return orders_client.ConfirmResult(ok=False, code="order_cancelled")
        self.confirmed.append((number, payment_id, amount, currency))
        if order["status"] == "pending_payment":
            order["status"] = "paid"
        return orders_client.ConfirmResult(ok=True)


@pytest.fixture
def orders(monkeypatch):
    fake = FakeOrders()
    monkeypatch.setattr(orders_client, "get_order", fake.get_order)
    monkeypatch.setattr(orders_client, "confirm_payment", fake.confirm_payment)
    return fake

import json
import os
import uuid
from datetime import datetime, timezone

# Configure before the app is imported (settings are read once).
# Tests use their own database and never touch notifications_db, even inside the container.
os.environ["DB_NAME"] = os.environ.get("TEST_DB_NAME", "notifications_test")
os.environ.setdefault("DB_USER", "shopverse")
os.environ.setdefault("DB_PASSWORD", "shopverse")

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import get_engine, get_sessionmaker  # noqa: E402
from app.handlers import build_handlers  # noqa: E402
from app.messaging import process  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CUSTOMER = uuid.UUID("11111111-1111-4111-8111-111111111111")
CUSTOMER_EMAIL = "customer@example.com"


class FakeMailer:
    """Records what would be sent. Set fail_with to make the next sends fail."""

    def __init__(self):
        self.sent = []
        self.fail_with = None

    def send(self, to_address, email):
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append((to_address, email))


def envelope(type_, data, *, key="k", message_id=None):
    return {
        "id": str(message_id or uuid.uuid4()),
        "type": type_,
        "source": "test",
        "occurred_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "key": key,
        "data": data,
    }


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
        conn.execute(text("TRUNCATE recipients, order_customers, notification_log, processed_messages"))


@pytest.fixture
def mailer():
    return FakeMailer()


@pytest.fixture
def handlers(mailer):
    return build_handlers(get_settings(), mailer)


@pytest.fixture
def deliver(handlers):
    """deliver(topic, type_, data, message_id=None) runs one message through the same
    process() the worker uses, and returns its outcome ("handled", "duplicate", "ignored")."""

    def _deliver(topic, type_, data, *, key="k", message_id=None):
        message = envelope(type_, data, key=key, message_id=message_id)
        return process(get_sessionmaker(), handlers, topic, json.dumps(message).encode())

    return _deliver


@pytest.fixture
def customer_registered(deliver):
    """Gives the test customer contact details, as users.events would."""
    deliver("users.events", "UserRegistered", {
        "user_id": str(CUSTOMER), "email": CUSTOMER_EMAIL, "first_name": "Nia", "last_name": "Khan",
    }, key=str(CUSTOMER))
    return CUSTOMER

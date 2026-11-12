"""The payments worker: `python -m app.worker`.

Reads refund commands from the checkout saga and publishes payment events from the
outbox. The HTTP service and the worker share the database but not a process, so a
slow Kafka never holds up a customer's payment or a Stripe webhook.
"""

import logging

from . import service
from .config import get_settings
from .db import get_sessionmaker
from .messaging import Worker
from .providers import get_provider


def refund_payment(db, envelope):
    data = envelope["data"]
    service.refund_order(db, get_provider(), order_number=data["order_number"], reason=data.get("reason", ""))


HANDLERS = {"RefundPayment": refund_payment}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    Worker(
        group="payments",
        topics=["payments.commands"],
        handlers=HANDLERS,
        sessions=get_sessionmaker(),
        bootstrap=settings.kafka_bootstrap_servers,
    ).run()


if __name__ == "__main__":
    main()

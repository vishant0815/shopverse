"""The notifications worker: `python -m app.worker`.

Reads order, payment and user events from Kafka and sends the customer emails. It has no
HTTP port: nothing calls it, it only reacts to events.
"""

import logging

from .config import get_settings
from .db import get_sessionmaker
from .handlers import build_handlers
from .mailer import SmtpMailer
from .messaging import TOPICS, Worker


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    Worker(
        group="notifications",
        topics=TOPICS,
        handlers=build_handlers(settings, SmtpMailer(settings)),
        sessions=get_sessionmaker(),
        bootstrap=settings.kafka_bootstrap_servers,
        wait_limit=settings.recipient_wait_seconds,
    ).run()


if __name__ == "__main__":
    main()

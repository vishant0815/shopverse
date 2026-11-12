"""The inventory worker: `python -m app.worker`.

Reads catalogue events (to know which variants exist and who sells them) and stock
commands from the checkout saga, and publishes its replies from the outbox.
"""

import logging

from .config import get_settings
from .db import get_sessionmaker
from .messaging import Worker
from .stock import HANDLERS


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    Worker(
        group="inventory",
        topics=["catalog.variants", "inventory.commands"],
        handlers=HANDLERS,
        sessions=get_sessionmaker(),
        bootstrap=settings.kafka_bootstrap_servers,
    ).run()


if __name__ == "__main__":
    main()

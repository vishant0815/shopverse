"""The search worker: `python -m app.worker`.

Reads catalogue product events and keeps the search index in step with them.
"""

import logging
import signal
import time

from elasticsearch import Elasticsearch

from .config import get_settings
from .consumer import SearchConsumer
from .index import ensure_index

log = logging.getLogger("search.worker")


def wait_for_index(es: Elasticsearch, name: str, delay: float = 2.0) -> None:
    """Create the index once Elasticsearch is reachable."""
    while True:
        try:
            ensure_index(es, name)
            return
        except Exception as exc:
            log.warning("search index not ready (%s); retrying in %ss", exc, delay)
            time.sleep(delay)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    es = Elasticsearch(settings.es_url)
    wait_for_index(es, settings.search_index)
    consumer = SearchConsumer(
        es=es,
        index=settings.search_index,
        bootstrap=settings.kafka_bootstrap_servers,
        group=settings.kafka_group,
        topics=[settings.products_topic],
    )
    signal.signal(signal.SIGTERM, lambda *_: consumer.stop())
    signal.signal(signal.SIGINT, lambda *_: consumer.stop())
    consumer.run()


if __name__ == "__main__":
    main()

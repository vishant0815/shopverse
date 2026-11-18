"""Clickstream collector: accepts storefront events and queues them on Kafka for Spark."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .messaging import ensure_topics
from .routes import get_publisher, router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

settings = get_settings()  # fails fast on bad configuration


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Kafka doesn't create topics on its own here, so the collector makes its topic first.
    ensure_topics(settings.kafka_bootstrap_servers, settings.clickstream_topic)
    yield
    get_publisher().close()


app = FastAPI(
    title="Shopverse clickstream collector",
    description="Accepts product views, searches and add-to-cart events from the storefront and queues them for Spark.",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "service": "clickstream"}

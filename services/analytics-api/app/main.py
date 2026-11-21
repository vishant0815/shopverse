"""Shopverse analytics API: the seller dashboard's numbers, read from the tables the Spark job writes."""

import logging

from fastapi import FastAPI

from .config import get_settings
from .routes import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

get_settings()  # fails fast on bad configuration

app = FastAPI(
    title="Shopverse analytics API",
    description="Seller dashboard numbers: product views, add-to-carts and units sold, by day and by product.",
    version="1.0.0",
)
app.include_router(router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "service": "analytics"}

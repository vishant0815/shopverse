import logging

from fastapi import FastAPI

from .config import get_settings
from .routes import payments, webhooks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

settings = get_settings()  # fails fast on bad configuration

app = FastAPI(
    title="Shopverse payments service",
    description="Takes payments for orders through Stripe (test mode) or a fake provider for local demos.",
    version="1.0.0",
)
app.include_router(payments.router)
app.include_router(webhooks.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "service": "payments", "provider": settings.payment_provider}

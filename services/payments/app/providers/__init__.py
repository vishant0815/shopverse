from functools import lru_cache

from ..config import get_settings
from .base import CreatedPayment, PaymentEvent, PaymentProvider, ProviderError


@lru_cache
def get_provider() -> PaymentProvider:
    settings = get_settings()
    if settings.payment_provider == "stripe":
        from .stripe_provider import StripeProvider

        return StripeProvider(settings.stripe_secret_key, settings.stripe_webhook_secret)
    from .fake_provider import FakeProvider

    return FakeProvider()


__all__ = ["CreatedPayment", "PaymentEvent", "PaymentProvider", "ProviderError", "get_provider"]

"""The interface every payment provider implements.

Keeping Stripe behind this interface means the rest of the service doesn't know or care
which provider is used, and tests and local demos can run without a Stripe account.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


class ProviderError(Exception):
    """The provider rejected a request or couldn't be reached."""


@dataclass
class CreatedPayment:
    provider_payment_id: str
    client_secret: str


@dataclass
class PaymentEvent:
    """A provider webhook, reduced to what this service needs."""

    event_id: str
    type: str                  # "succeeded", "failed" or "other"
    provider_payment_id: str
    amount_minor: int
    currency: str
    error_message: str = ""


class PaymentProvider(ABC):
    name: str

    @abstractmethod
    def create_payment(self, *, amount_minor: int, currency: str, order_number: str) -> CreatedPayment:
        """Create a payment the customer can complete in the browser."""

    @abstractmethod
    def parse_webhook(self, payload: bytes, signature: str) -> PaymentEvent:
        """Verify the webhook really came from the provider and parse it.
        Raises ValueError if the signature is missing or wrong."""

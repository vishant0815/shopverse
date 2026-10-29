"""A stand-in provider for local development and demos: no Stripe account needed.

Payments are completed by calling the simulate endpoint, which produces the same
kind of event a real webhook would and runs it through exactly the same code.
"""

import secrets
import uuid

from .base import CreatedPayment, PaymentEvent, PaymentProvider


class FakeProvider(PaymentProvider):
    name = "fake"

    def create_payment(self, *, amount_minor, currency, order_number):
        payment_id = f"fake_pi_{uuid.uuid4().hex[:24]}"
        return CreatedPayment(provider_payment_id=payment_id, client_secret=f"{payment_id}_secret_{secrets.token_hex(12)}")

    def parse_webhook(self, payload, signature):
        raise ValueError("The fake provider has no webhooks; use the simulate endpoint.")

    @staticmethod
    def simulated_event(provider_payment_id, amount_minor, currency, outcome):
        return PaymentEvent(
            event_id=f"fake_evt_{uuid.uuid4().hex}",
            type=outcome,
            provider_payment_id=provider_payment_id,
            amount_minor=amount_minor,
            currency=currency,
            error_message="Your card was declined. (simulated)" if outcome == "failed" else "",
        )

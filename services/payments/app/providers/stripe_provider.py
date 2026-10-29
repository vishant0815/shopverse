import stripe

from .base import CreatedPayment, PaymentEvent, PaymentProvider, ProviderError

EVENT_TYPES = {
    "payment_intent.succeeded": "succeeded",
    "payment_intent.payment_failed": "failed",
}


class StripeProvider(PaymentProvider):
    name = "stripe"

    def __init__(self, secret_key: str, webhook_secret: str):
        self.client = stripe.StripeClient(secret_key)
        self.webhook_secret = webhook_secret

    def create_payment(self, *, amount_minor, currency, order_number):
        try:
            intent = self.client.v1.payment_intents.create(
                params={
                    "amount": amount_minor,
                    "currency": currency.lower(),
                    "automatic_payment_methods": {"enabled": True},
                    "metadata": {"order_number": order_number},
                    "description": f"Shopverse order {order_number}",
                },
                # Stripe's own idempotency: retrying for the same order can't create a second intent.
                options={"idempotency_key": f"shopverse-order-{order_number}"},
            )
        except stripe.StripeError as exc:
            raise ProviderError(str(exc)) from exc
        return CreatedPayment(provider_payment_id=intent.id, client_secret=intent.client_secret)

    def parse_webhook(self, payload, signature):
        try:
            # Checks the HMAC signature and rejects events older than 5 minutes (replay protection).
            event = stripe.Webhook.construct_event(payload, signature, self.webhook_secret)
        except (stripe.SignatureVerificationError, ValueError) as exc:
            raise ValueError("Invalid Stripe signature") from exc

        intent = event["data"]["object"]
        error = intent.get("last_payment_error") or {}
        return PaymentEvent(
            event_id=event["id"],
            type=EVENT_TYPES.get(event["type"], "other"),
            provider_payment_id=intent.get("id", ""),
            amount_minor=intent.get("amount_received") or intent.get("amount") or 0,
            currency=(intent.get("currency") or "").upper(),
            error_message=(error.get("message") or "")[:255],
        )

"""Stripe webhooks with real signatures, and the Stripe provider itself."""

import hashlib
import hmac
import json
import time
import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.providers.stripe_provider import StripeProvider
from app.routes import payments as payment_routes
from app.routes import webhooks as webhook_routes

WEBHOOK = "/api/v1/webhooks/stripe"
WEBHOOK_SECRET = "whsec_test_secret_for_signatures"


class RecordingStripe(StripeProvider):
    """The real Stripe provider (real signature checks), with intent creation recorded instead of sent."""

    def __init__(self):
        super().__init__("sk_test_dummy", WEBHOOK_SECRET)
        self.created = []

        def create(params, options):
            self.created.append((params, options))
            intent_id = f"pi_{uuid.uuid4().hex[:24]}"
            return SimpleNamespace(id=intent_id, client_secret=f"{intent_id}_secret_abc")

        self.client = SimpleNamespace(v1=SimpleNamespace(payment_intents=SimpleNamespace(create=create)))


@pytest.fixture
def stripe_provider(monkeypatch):
    provider = RecordingStripe()
    monkeypatch.setattr(payment_routes, "get_provider", lambda: provider)
    monkeypatch.setattr(webhook_routes, "get_provider", lambda: provider)
    return provider


def sign(payload: bytes, secret=WEBHOOK_SECRET, timestamp=None):
    timestamp = timestamp or int(time.time())
    signature = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


def stripe_event(intent_id, event_type="payment_intent.succeeded", amount=5998, currency="gbp", event_id=None):
    return json.dumps({
        "id": event_id or f"evt_{uuid.uuid4().hex[:24]}",
        "object": "event",
        "type": event_type,
        "data": {"object": {
            "id": intent_id, "object": "payment_intent", "amount": amount, "amount_received": amount,
            "currency": currency,
            "last_payment_error": {"message": "Your card was declined."} if "failed" in event_type else None,
        }},
    }).encode()


def deliver(client, payload, signature=None):
    return client.post(WEBHOOK, content=payload,
                       headers={"Stripe-Signature": signature if signature is not None else sign(payload),
                                "Content-Type": "application/json"})


@pytest.fixture
def started(customer, orders, stripe_provider):
    """An order with a Stripe payment started. Returns (order number, intent id)."""
    number = orders.add(customer.id, total="59.98")
    body = customer.post("/api/v1/payments", json={"order_number": number}).json()
    intent_id = body["client_secret"].split("_secret_")[0]
    return number, intent_id


class TestCreatingIntents:
    def test_intent_uses_pence_lowercase_currency_and_idempotency_key(self, started, stripe_provider):
        number, _ = started
        params, options = stripe_provider.created[0]

        assert params["amount"] == 5998
        assert params["currency"] == "gbp"
        assert params["metadata"] == {"order_number": number}
        assert options == {"idempotency_key": f"shopverse-order-{number}"}


class TestWebhooks:
    def test_succeeded_event_marks_order_paid(self, client, started, orders):
        number, intent_id = started

        response = deliver(client, stripe_event(intent_id))

        assert response.status_code == 200
        assert response.json()["outcome"] == "succeeded"
        assert orders.orders[number]["status"] == "paid"

    def test_failed_event_is_recorded(self, client, customer, started, orders):
        number, intent_id = started

        deliver(client, stripe_event(intent_id, "payment_intent.payment_failed"))

        payment = customer.get(f"/api/v1/payments/{number}").json()
        assert payment["status"] == "failed"
        assert payment["last_error"] == "Your card was declined."

    @pytest.mark.parametrize("signature", [
        "",                                                     # missing
        "t=123,v1=deadbeef",                                    # nonsense
        None,                                                   # replaced below with a wrong secret
    ])
    def test_unsigned_or_forged_events_are_rejected(self, client, started, orders, signature):
        number, intent_id = started
        payload = stripe_event(intent_id)
        if signature is None:
            signature = sign(payload, secret="whsec_attacker")

        assert deliver(client, payload, signature).status_code == 400
        assert orders.orders[number]["status"] == "pending_payment"

    def test_tampered_payload_is_rejected(self, client, started, orders):
        number, intent_id = started
        signature = sign(stripe_event(intent_id, amount=5998))
        tampered = stripe_event(intent_id, amount=1)

        assert deliver(client, tampered, signature).status_code == 400

    def test_replayed_old_event_is_rejected(self, client, started):
        _, intent_id = started
        payload = stripe_event(intent_id)

        assert deliver(client, payload, sign(payload, timestamp=int(time.time()) - 600)).status_code == 400

    def test_duplicate_delivery_is_processed_once(self, client, started, orders):
        number, intent_id = started
        payload = stripe_event(intent_id, event_id="evt_same")

        first = deliver(client, payload)
        second = deliver(client, payload)

        assert first.json()["outcome"] == "succeeded"
        assert second.json()["outcome"] == "duplicate"
        assert len(orders.confirmed) == 1

    def test_amount_mismatch_never_marks_paid(self, client, customer, started, orders):
        number, intent_id = started

        response = deliver(client, stripe_event(intent_id, amount=100))

        assert response.json()["outcome"] == "amount_mismatch"
        assert orders.orders[number]["status"] == "pending_payment"
        assert customer.get(f"/api/v1/payments/{number}").json()["status"] == "amount_mismatch"

    def test_unknown_payment_is_acknowledged(self, client, stripe_provider):
        response = deliver(client, stripe_event("pi_not_ours"))

        assert response.status_code == 200
        assert response.json()["outcome"] == "unknown_payment"

    def test_other_event_types_are_ignored(self, client, started):
        _, intent_id = started

        response = deliver(client, stripe_event(intent_id, "payment_intent.created"))

        assert response.json()["outcome"] == "ignored"

    def test_orders_down_asks_stripe_to_retry(self, client, started, orders):
        number, intent_id = started
        payload = stripe_event(intent_id, event_id="evt_retry")
        orders.down = True

        assert deliver(client, payload).status_code == 503

        orders.down = False
        assert deliver(client, payload).json()["outcome"] == "succeeded"
        assert orders.orders[number]["status"] == "paid"

    def test_simulate_is_disabled_with_stripe(self, customer, started):
        number, _ = started

        assert customer.post(f"/api/v1/payments/{number}/simulate", json={"outcome": "succeeded"}).status_code == 404


def test_webhook_endpoint_is_off_with_fake_provider(client):
    assert client.post(WEBHOOK, content=b"{}").status_code == 404


class TestConfig:
    BASE = {"db_user": "u", "db_password": "p", "jwt_signing_key": "k" * 40}

    def test_live_stripe_keys_are_refused(self):
        with pytest.raises(ValidationError, match="test key"):
            Settings(**self.BASE, payment_provider="stripe", stripe_secret_key="sk_live_123",
                     stripe_webhook_secret="whsec_x")

    def test_stripe_needs_a_webhook_secret(self):
        with pytest.raises(ValidationError, match="WEBHOOK_SECRET"):
            Settings(**self.BASE, payment_provider="stripe", stripe_secret_key="sk_test_123")

    def test_short_signing_key_is_refused(self):
        with pytest.raises(ValidationError, match="32 characters"):
            Settings(**{**self.BASE, "jwt_signing_key": "short"})

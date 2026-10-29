import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from .models import Payment


class CreatePaymentRequest(BaseModel):
    order_number: str = Field(min_length=1, max_length=20, examples=["SV-20261029-K7Q2ZP"])


class PaymentOut(BaseModel):
    id: uuid.UUID
    order_number: str
    provider: str
    status: str
    amount: Decimal
    amount_minor: int
    currency: str
    last_error: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, payment: Payment) -> "PaymentOut":
        return cls(
            id=payment.id,
            order_number=payment.order_number,
            provider=payment.provider,
            status=payment.status.value,
            amount=payment.amount,
            amount_minor=payment.amount_minor,
            currency=payment.currency,
            last_error=payment.last_error,
            created_at=payment.created_at,
            updated_at=payment.updated_at,
        )


class PaymentStarted(PaymentOut):
    # The browser uses this with Stripe.js to show the card form. It's only
    # returned to the customer who owns the payment.
    client_secret: str

    @classmethod
    def of(cls, payment: Payment) -> "PaymentStarted":
        return cls(**PaymentOut.of(payment).model_dump(), client_secret=payment.client_secret)


class SimulateRequest(BaseModel):
    outcome: Literal["succeeded", "failed"]


class SimulateResponse(BaseModel):
    outcome: str
    payment: PaymentOut

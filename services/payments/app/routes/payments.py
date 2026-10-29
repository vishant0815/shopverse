from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import orders_client, service
from ..auth import CurrentUser, current_user
from ..db import get_db
from ..models import Payment
from ..providers import get_provider
from ..providers.fake_provider import FakeProvider
from ..schemas import CreatePaymentRequest, PaymentOut, PaymentStarted, SimulateRequest, SimulateResponse

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])


def payment_error(error: service.PaymentError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail={"code": error.code, "detail": error.detail})


@router.post("", response_model=PaymentStarted, status_code=status.HTTP_201_CREATED,
             responses={200: {"description": "Existing payment for this order returned"}})
def create_payment(body: CreatePaymentRequest, response: Response,
                   user: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    """Start paying for one of your orders. Calling it again returns the same payment."""
    try:
        payment, created = service.start_payment(
            db, get_provider(), order_number=body.order_number, user_id=user.id, customer_token=user.token
        )
    except service.PaymentError as error:
        raise payment_error(error)
    if not created:
        response.status_code = status.HTTP_200_OK
    return PaymentStarted.of(payment)


def own_payment(db: Session, order_number: str, user: CurrentUser) -> Payment:
    payment = db.scalar(select(Payment).where(Payment.order_number == order_number))
    # Someone else's payment looks exactly like a missing one.
    if payment is None or payment.user_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "not_found", "detail": "Payment not found."})
    return payment


@router.get("/{order_number}", response_model=PaymentOut)
def get_payment(order_number: str, user: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    """Payment status for one of your orders."""
    return PaymentOut.of(own_payment(db, order_number, user))


@router.post("/{order_number}/simulate", response_model=SimulateResponse)
def simulate(order_number: str, body: SimulateRequest,
             user: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    """Fake provider only: complete or fail a payment, as if the provider's webhook had arrived."""
    if not isinstance(get_provider(), FakeProvider):
        raise HTTPException(status_code=404, detail={"code": "not_found", "detail": "Not available."})
    payment = own_payment(db, order_number, user)
    event = FakeProvider.simulated_event(payment.provider_payment_id, payment.amount_minor, payment.currency, body.outcome)
    try:
        outcome = service.handle_event(db, event)
    except orders_client.OrdersUnavailable:
        raise HTTPException(status_code=503, detail={"code": "orders_unavailable",
                                                     "detail": "Orders service unavailable. Please try again."})
    db.refresh(payment)
    return SimulateResponse(outcome=outcome, payment=PaymentOut.of(payment))

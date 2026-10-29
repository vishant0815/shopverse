"""Client for the orders service."""

import logging
from dataclasses import dataclass
from decimal import Decimal

import httpx

from .auth import service_token
from .config import get_settings

logger = logging.getLogger(__name__)


class OrdersUnavailable(Exception):
    """The orders service couldn't be reached or answered with an unexpected error."""


class OrderNotFound(Exception):
    pass


@dataclass
class OrderInfo:
    number: str
    status: str
    total: Decimal
    currency: str


def _url(path: str) -> str:
    return f"{get_settings().orders_service_url.rstrip('/')}/api/v1/{path}"


def get_order(number: str, customer_token: str) -> OrderInfo:
    """Fetch an order *as the customer*, so the orders service applies its own ownership check:
    another customer's order comes back as 404."""
    try:
        response = httpx.get(
            _url(f"orders/{number}/"),
            headers={"Authorization": f"Bearer {customer_token}"},
            timeout=get_settings().orders_service_timeout,
        )
    except httpx.HTTPError as exc:
        logger.warning("Orders service unreachable: %s", exc)
        raise OrdersUnavailable from exc

    if response.status_code == 404:
        raise OrderNotFound
    if response.status_code != 200:
        logger.warning("Orders service returned %s for order %s", response.status_code, number)
        raise OrdersUnavailable
    data = response.json()
    return OrderInfo(number=data["number"], status=data["status"], total=Decimal(data["total"]), currency=data["currency"])


@dataclass
class ConfirmResult:
    ok: bool
    code: str = ""


def confirm_payment(number: str, payment_id: str, amount: Decimal, currency: str) -> ConfirmResult:
    """Tell the orders service a payment succeeded. Safe to repeat."""
    try:
        response = httpx.post(
            _url(f"internal/orders/{number}/payment-confirmed/"),
            json={"payment_id": payment_id, "amount": str(amount), "currency": currency},
            headers={"Authorization": f"Bearer {service_token()}"},
            timeout=get_settings().orders_service_timeout,
        )
    except httpx.HTTPError as exc:
        logger.warning("Orders service unreachable while confirming %s: %s", number, exc)
        raise OrdersUnavailable from exc

    if response.status_code == 200:
        return ConfirmResult(ok=True)
    if response.status_code == 409:
        return ConfirmResult(ok=False, code=response.json().get("code", "conflict"))
    logger.warning("Orders service returned %s while confirming %s", response.status_code, number)
    raise OrdersUnavailable

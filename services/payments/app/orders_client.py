"""Client for the orders service."""

import logging
from dataclasses import dataclass
from decimal import Decimal

import httpx

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

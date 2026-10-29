"""Client for the product service.

Prices are always looked up here, at the moment they matter, and never taken from the
client. A user can't change what they pay by editing a request.
"""

import logging
from decimal import Decimal

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


class CatalogUnavailable(Exception):
    """The product service could not be reached or gave an unusable answer."""


def lookup_variants(variant_ids):
    """Return {variant_id (str): variant info} for every id that is currently buyable.

    Ids that are missing from the result are unavailable (unknown, inactive or not published).
    """
    ids = [str(v) for v in dict.fromkeys(variant_ids)]
    if not ids:
        return {}
    url = f"{settings.PRODUCTS_SERVICE_URL.rstrip('/')}/api/v1/variants/lookup/"
    try:
        response = httpx.get(url, params={"ids": ",".join(ids)}, timeout=settings.PRODUCTS_SERVICE_TIMEOUT)
        response.raise_for_status()
        results = response.json()["results"]
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning("Product service lookup failed: %s", exc)
        raise CatalogUnavailable from exc

    variants = {}
    for item in results:
        item["price"] = Decimal(item["price"])
        variants[str(item["variant_id"])] = item
    return variants

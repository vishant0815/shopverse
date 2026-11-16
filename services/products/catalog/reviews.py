"""Product reviews: who may write one, how a product's rating is kept, and what a change to a review causes.

Only a customer with a delivered order for a product may review it. That fact lives in the orders
service, so it is asked over HTTP. When the orders service can't answer, nothing is written.
"""

import logging
from decimal import ROUND_HALF_UP, Decimal
from functools import partial

import httpx
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count

from . import events
from .models import Product, Review

logger = logging.getLogger(__name__)

# The limits the storefront and the API both enforce.
TITLE_MAX = 120
BODY_MIN = 20
BODY_MAX = 2000
# The newest visible reviews a product page shows. Older ones are not paged yet.
LIST_LIMIT = 50


class PurchaseCheckUnavailable(Exception):
    """The orders service could not say whether the customer bought the product."""


class NotVerifiedBuyer(Exception):
    """The customer has no delivered order that contains the product."""


class AlreadyReviewed(Exception):
    """The customer already has a review of this product."""


def verified_purchase(user_id, product_id) -> bool:
    """Ask the orders service whether this customer has a delivered order containing the product."""
    url = f"{settings.ORDERS_SERVICE_URL.rstrip('/')}/api/v1/internal/verified-purchase/"
    try:
        response = httpx.get(
            url,
            params={"user_id": str(user_id), "product_id": str(product_id)},
            timeout=settings.ORDERS_SERVICE_TIMEOUT,
        )
        response.raise_for_status()
        return bool(response.json()["verified"])
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning("Orders service purchase check failed: %s", exc)
        raise PurchaseCheckUnavailable from exc


def _average(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _visible(product: Product):
    return product.reviews.filter(status=Review.Status.VISIBLE)


def summary(product: Product) -> dict:
    """The average, the count, and how many reviews sit at each star level. Visible reviews only."""
    visible = _visible(product)
    totals = visible.aggregate(count=Count("id"), average=Avg("rating"))
    distribution = {str(stars): 0 for stars in range(1, 6)}
    # order_by() clears the model's default ordering, so the GROUP BY is just the rating.
    for row in visible.order_by().values("rating").annotate(n=Count("id")):
        distribution[str(row["rating"])] = row["n"]
    count = totals["count"]
    average = _average(totals["average"]) if count else None
    return {
        "average": str(average) if average is not None else None,
        "count": count,
        "distribution": distribution,
    }


def refresh_rating(product: Product) -> None:
    """Recalculate the stored rating from the visible reviews, then re-send the product to search."""
    totals = _visible(product).aggregate(count=Count("id"), average=Avg("rating"))
    count = totals["count"]
    average = _average(totals["average"]) if count else None
    Product.objects.filter(pk=product.pk).update(rating_average=average, rating_count=count)
    # Announce only after the commit, so search never gets a rating that was rolled back.
    transaction.on_commit(partial(events.announce_product, product.pk))


def save_review(review: Review) -> Review:
    """Save an edited review and bring the product's rating up to date."""
    with transaction.atomic():
        review.save()
        refresh_rating(review.product)
    return review


def create_review(product: Product, user_id, *, rating: int, title: str, body: str) -> Review:
    if product.reviews.filter(user_id=user_id).exists():
        raise AlreadyReviewed
    if not verified_purchase(user_id, product.pk):
        raise NotVerifiedBuyer
    try:
        with transaction.atomic():
            review = Review.objects.create(product=product, user_id=user_id, rating=rating, title=title, body=body)
            refresh_rating(product)
    except IntegrityError as exc:
        # The same customer's second request got past the check above at the same moment.
        raise AlreadyReviewed from exc
    return review

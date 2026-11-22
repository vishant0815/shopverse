"""Storefront recommendations: the products shoppers most often bought in the same order as a product.

Anyone can read these, so there is no token check. The Spark job refreshes the pairs every few
minutes, and a pair shared by fewer than MIN_SHARED_ORDERS orders is not suggested.
"""

import uuid

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Response, status

from .db import get_connection

router = APIRouter(prefix="/api/v1/recommendations", tags=["recommendations"])

# How many products the product page suggests.
ITEM_LIMIT = 3
# Two products must have been in at least this many orders together before one is suggested.
MIN_SHARED_ORDERS = 2
# The job refreshes the pairs every few minutes, so a cache may keep an answer for two.
CACHE_SECONDS = 120

BOUGHT_TOGETHER_SQL = """
    SELECT l.product_id, l.name, l.slug, l.image_url
    FROM product_pairs p
    JOIN product_listings l ON l.product_id = p.related_id
    WHERE p.product_id = %(product)s AND p.shared_orders >= %(minimum)s
    ORDER BY p.shared_orders DESC, l.name
    LIMIT %(limit)s
"""


@router.get("/products/{product_id}/bought-together")
def bought_together(
    product_id: uuid.UUID,
    response: Response,
    conn: psycopg.Connection = Depends(get_connection),
):
    """Up to three products shoppers often bought in the same order as this one, most shared first."""
    try:
        rows = conn.execute(
            BOUGHT_TOGETHER_SQL,
            {"product": product_id, "minimum": MIN_SHARED_ORDERS, "limit": ITEM_LIMIT},
        ).fetchall()
    except psycopg.errors.UndefinedTable:
        # The Spark job creates these tables when it starts, so they can be missing for a while.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Recommendations are not ready yet. Try again shortly.",
        )
    response.headers["Cache-Control"] = f"public, max-age={CACHE_SECONDS}"
    items = [
        {"product_id": str(pid), "name": name, "slug": slug, "image_url": image_url}
        for pid, name, slug, image_url in rows
    ]
    return {"product_id": str(product_id), "items": items}

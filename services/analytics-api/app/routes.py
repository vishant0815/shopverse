"""The seller analytics endpoint."""

import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status

from .auth import seller_id
from .config import get_settings
from .queries import seller_summary, window

router = APIRouter(prefix="/api/v1/seller/analytics", tags=["seller analytics"])


def get_connection() -> Iterator[psycopg.Connection]:
    # Reads only, so each statement commits by itself and nothing is held open between requests.
    conn = psycopg.connect(get_settings().database_url, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


@router.get("/")
def seller_analytics(
    # Query values arrive as text, so the two allowed lengths are written as text too.
    days: Literal["7", "30"] = "7",
    seller: uuid.UUID = Depends(seller_id),
    conn: psycopg.Connection = Depends(get_connection),
):
    """The signed-in seller's views, add-to-carts and units sold, by day and by product."""
    span = int(days)
    start, end = window(datetime.now(timezone.utc).date(), span)
    try:
        summary = seller_summary(conn, seller, start, end)
    except psycopg.errors.UndefinedTable:
        # The Spark job creates these tables when it starts, so they can be missing for a while.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Analytics are not ready yet. Try again shortly.",
        )
    return summary | {"days": span}

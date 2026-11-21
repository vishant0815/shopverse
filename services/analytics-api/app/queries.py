"""Reads for the seller dashboard. Every query is limited to one seller's products.

The Spark job writes product_listings (which seller owns each product) and product_daily (the
day's views, add-to-carts and units sold). Joining them here means a seller can only ever see
their own numbers, whatever product ids the page asks about.
"""

import uuid
from datetime import date, timedelta

import psycopg

# How many products the table shows. The totals always cover every product of the seller.
PRODUCT_LIMIT = 50

DAILY_SQL = """
    SELECT d.day, SUM(d.views), SUM(d.add_to_carts), SUM(d.units_sold)
    FROM product_daily d
    JOIN product_listings l ON l.product_id = d.product_id
    WHERE l.seller_id = %(seller)s AND d.day BETWEEN %(start)s AND %(end)s
    GROUP BY d.day
"""

PRODUCTS_SQL = """
    SELECT l.product_id, l.name, l.slug, l.image_url,
           SUM(d.views), SUM(d.add_to_carts), SUM(d.units_sold)
    FROM product_daily d
    JOIN product_listings l ON l.product_id = d.product_id
    WHERE l.seller_id = %(seller)s AND d.day BETWEEN %(start)s AND %(end)s
    GROUP BY l.product_id, l.name, l.slug, l.image_url
    ORDER BY SUM(d.units_sold) DESC, SUM(d.views) DESC, l.name
    LIMIT %(limit)s
"""


def window(today: date, days: int) -> tuple[date, date]:
    """The first and last UTC day of the range, ending today."""
    return today - timedelta(days=days - 1), today


def seller_summary(conn: psycopg.Connection, seller: uuid.UUID, start: date, end: date) -> dict:
    params = {"seller": seller, "start": start, "end": end}
    with conn.cursor() as cursor:
        daily_rows = cursor.execute(DAILY_SQL, params).fetchall()
        product_rows = cursor.execute(PRODUCTS_SQL, params | {"limit": PRODUCT_LIMIT}).fetchall()

    by_day = {day: (int(views), int(carts), int(sold)) for day, views, carts, sold in daily_rows}
    daily = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        views, carts, sold = by_day.get(day, (0, 0, 0))
        daily.append({"date": day.isoformat(), "views": views, "add_to_carts": carts, "units_sold": sold})

    views = sum(row["views"] for row in daily)
    carts = sum(row["add_to_carts"] for row in daily)
    sold = sum(row["units_sold"] for row in daily)
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "totals": {
            "views": views,
            "add_to_carts": carts,
            "units_sold": sold,
            # Share of product views that led to an add to basket. None when nothing was viewed.
            "add_to_cart_rate": round(carts / views, 3) if views else None,
        },
        "daily": daily,
        "products": [
            {
                "product_id": str(product_id),
                "name": name,
                "slug": slug,
                "image_url": image_url,
                "views": int(product_views),
                "add_to_carts": int(product_carts),
                "units_sold": int(product_sold),
            }
            for product_id, name, slug, image_url, product_views, product_carts, product_sold in product_rows
        ],
    }

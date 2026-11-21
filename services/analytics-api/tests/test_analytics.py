import uuid
from datetime import timedelta

import psycopg

from .conftest import SCHEMA, TEST_DATABASE_URL, auth, seed_day, seed_product, today

URL = "/api/v1/seller/analytics/"


def test_a_seller_sees_totals_for_their_own_products_only(client, db):
    seller, other = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(db, autocommit=True) as conn:
        mine = seed_product(conn, seller, "Desk Lamp")
        theirs = seed_product(conn, other, "Chair")
        seed_day(conn, mine, today(), views=3, carts=1, sold=2)
        seed_day(conn, theirs, today(), views=100, carts=50, sold=9)

    body = client.get(URL, headers=auth(seller)).json()

    assert body["totals"] == {"views": 3, "add_to_carts": 1, "units_sold": 2, "add_to_cart_rate": 0.333}
    assert [p["product_id"] for p in body["products"]] == [str(mine)]
    assert body["products"][0]["name"] == "Desk Lamp"


def test_the_daily_series_covers_every_day_of_the_range_oldest_first(client, db):
    seller = uuid.uuid4()
    with psycopg.connect(db, autocommit=True) as conn:
        product = seed_product(conn, seller, "Desk Lamp")
        seed_day(conn, product, today() - timedelta(days=2), views=4, carts=0, sold=1)

    week = client.get(URL, headers=auth(seller)).json()
    month = client.get(URL, params={"days": 30}, headers=auth(seller)).json()

    assert week["days"] == 7 and len(week["daily"]) == 7
    assert week["daily"][0]["date"] == (today() - timedelta(days=6)).isoformat()
    assert week["daily"][-1]["date"] == today().isoformat()
    assert week["daily"][4] == {"date": (today() - timedelta(days=2)).isoformat(), "views": 4, "add_to_carts": 0, "units_sold": 1}
    assert week["daily"][0] == {"date": (today() - timedelta(days=6)).isoformat(), "views": 0, "add_to_carts": 0, "units_sold": 0}
    assert len(month["daily"]) == 30


def test_products_are_listed_by_units_sold(client, db):
    seller = uuid.uuid4()
    with psycopg.connect(db, autocommit=True) as conn:
        quiet = seed_product(conn, seller, "Quiet Mug")
        busy = seed_product(conn, seller, "Busy Lamp")
        seed_day(conn, quiet, today(), views=50, carts=0, sold=0)
        seed_day(conn, busy, today(), views=5, carts=2, sold=7)

    products = client.get(URL, headers=auth(seller)).json()["products"]

    assert [p["name"] for p in products] == ["Busy Lamp", "Quiet Mug"]


def test_the_add_to_cart_rate_is_empty_when_nothing_was_viewed(client, db):
    seller = uuid.uuid4()
    with psycopg.connect(db, autocommit=True) as conn:
        product = seed_product(conn, seller, "Desk Lamp")
        seed_day(conn, product, today(), views=0, carts=0, sold=3)

    totals = client.get(URL, headers=auth(seller)).json()["totals"]

    assert totals["add_to_cart_rate"] is None
    assert totals["units_sold"] == 3


def test_customers_and_bad_tokens_are_refused(client):
    seller = uuid.uuid4()

    assert client.get(URL).status_code == 401
    assert client.get(URL, headers=auth(seller, role="customer")).status_code == 403
    assert client.get(URL, headers=auth(seller, token_type="refresh")).status_code == 401
    assert client.get(URL, headers=auth(seller, expires_in=-10)).status_code == 401
    assert client.get(URL, headers={"Authorization": "Bearer not-a-token"}).status_code == 401


def test_only_one_week_or_one_month_can_be_asked_for(client):
    response = client.get(URL, params={"days": 14}, headers=auth(uuid.uuid4()))

    assert response.status_code == 422


def test_missing_tables_answer_503_until_the_job_creates_them(client, db):
    seller = uuid.uuid4()
    with psycopg.connect(db, autocommit=True) as conn:
        conn.execute("DROP TABLE product_daily, product_listings")
    try:
        response = client.get(URL, headers=auth(seller))
    finally:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
            conn.execute(SCHEMA.read_text(encoding="utf-8"))

    assert response.status_code == 503


def test_health_says_the_service_is_up(client):
    assert client.get("/health").json() == {"status": "ok", "service": "analytics"}

import uuid

import psycopg

from .conftest import seed_product

URL = "/api/v1/recommendations/products/{}/bought-together"


def seed_pair(conn, product: uuid.UUID, related: uuid.UUID, shared_orders: int) -> None:
    conn.execute(
        "INSERT INTO product_pairs (product_id, related_id, shared_orders) VALUES (%s, %s, %s)",
        (product, related, shared_orders),
    )


def test_the_most_shared_products_come_first_with_their_details(client, db):
    seller = uuid.uuid4()
    with psycopg.connect(db, autocommit=True) as conn:
        lamp = seed_product(conn, seller, "Desk Lamp")
        mug = seed_product(conn, seller, "Quiet Mug")
        chair = seed_product(conn, seller, "Chair")
        seed_pair(conn, lamp, mug, 5)
        seed_pair(conn, lamp, chair, 9)

    body = client.get(URL.format(lamp)).json()

    assert body["product_id"] == str(lamp)
    assert body["items"] == [
        {"product_id": str(chair), "name": "Chair", "slug": "chair", "image_url": ""},
        {"product_id": str(mug), "name": "Quiet Mug", "slug": "quiet-mug", "image_url": ""},
    ]


def test_a_pair_shared_by_only_one_order_is_not_suggested(client, db):
    seller = uuid.uuid4()
    with psycopg.connect(db, autocommit=True) as conn:
        lamp = seed_product(conn, seller, "Desk Lamp")
        mug = seed_product(conn, seller, "Quiet Mug")
        seed_pair(conn, lamp, mug, 1)

    assert client.get(URL.format(lamp)).json()["items"] == []


def test_at_most_three_products_are_suggested(client, db):
    seller = uuid.uuid4()
    with psycopg.connect(db, autocommit=True) as conn:
        lamp = seed_product(conn, seller, "Desk Lamp")
        for shared in range(2, 7):  # two to six shared orders
            seed_pair(conn, lamp, seed_product(conn, seller, f"Item {shared}"), shared)

    items = client.get(URL.format(lamp)).json()["items"]

    assert [item["name"] for item in items] == ["Item 6", "Item 5", "Item 4"]


def test_a_related_product_without_a_listing_is_skipped(client, db):
    seller = uuid.uuid4()
    with psycopg.connect(db, autocommit=True) as conn:
        lamp = seed_product(conn, seller, "Desk Lamp")
        seed_pair(conn, lamp, uuid.uuid4(), 4)  # no listing exists for this product

    assert client.get(URL.format(lamp)).json()["items"] == []


def test_anyone_can_read_them_and_the_answer_may_be_cached_briefly(client, db):
    seller = uuid.uuid4()
    with psycopg.connect(db, autocommit=True) as conn:
        lamp = seed_product(conn, seller, "Desk Lamp")
        mug = seed_product(conn, seller, "Quiet Mug")
        seed_pair(conn, lamp, mug, 2)

    response = client.get(URL.format(lamp))  # no token sent

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "public, max-age=120"
    assert [item["name"] for item in response.json()["items"]] == ["Quiet Mug"]


def test_an_unknown_product_has_no_suggestions(client):
    response = client.get(URL.format(uuid.uuid4()))

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_a_malformed_product_id_is_refused(client):
    assert client.get("/api/v1/recommendations/products/not-a-uuid/bought-together").status_code == 422


def test_the_answer_says_not_ready_while_the_job_has_not_created_its_tables(client, db):
    with psycopg.connect(db, autocommit=True) as conn:
        conn.execute("DROP TABLE product_pairs")

    response = client.get(URL.format(uuid.uuid4()))

    assert response.status_code == 503

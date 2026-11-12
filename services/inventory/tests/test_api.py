import uuid

from .conftest import as_user


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "service": "inventory"}


# Availability (public) -----------------------------------------------------------------

def test_anyone_can_see_what_is_available(client, add_stock):
    lamp, chair, gone = add_stock(on_hand=5, reserved=2), add_stock(on_hand=0), add_stock(on_hand=9, active=False)
    ghost = uuid.uuid4()

    response = client.get("/api/v1/inventory/availability", params={"variant_ids": f"{lamp},{chair},{gone},{ghost}"})

    assert response.status_code == 200
    found = {r["variant_id"]: r["available"] for r in response.json()["results"]}
    assert found == {str(lamp): 3, str(chair): 0, str(gone): 0}  # unknown ids are left out


def test_availability_rejects_bad_ids(client):
    assert client.get("/api/v1/inventory/availability", params={"variant_ids": "nope"}).status_code == 400
    many = ",".join(str(uuid.uuid4()) for _ in range(101))
    assert client.get("/api/v1/inventory/availability", params={"variant_ids": many}).status_code == 400


# Stock levels (sellers and admins) -----------------------------------------------------

def test_a_seller_sees_only_their_own_stock(client, add_stock):
    seller = uuid.uuid4()
    mine, theirs = add_stock(on_hand=5, reserved=1, seller_id=seller, sku="MINE"), add_stock(on_hand=7)

    response = client.get("/api/v1/inventory/stock", params={"variant_ids": f"{mine},{theirs}"},
                          headers=as_user(seller))

    assert response.json()["results"] == [
        {"variant_id": str(mine), "sku": "MINE", "on_hand": 5, "reserved": 1, "available": 4}]


def test_an_admin_sees_all_stock(client, add_stock):
    a, b = add_stock(on_hand=1), add_stock(on_hand=2)

    response = client.get("/api/v1/inventory/stock", params={"variant_ids": f"{a},{b}"},
                          headers=as_user(role="admin"))

    assert len(response.json()["results"]) == 2


def test_customers_and_strangers_cannot_see_stock_levels(client, add_stock):
    lamp = add_stock(on_hand=1)
    params = {"variant_ids": str(lamp)}

    assert client.get("/api/v1/inventory/stock", params=params).status_code == 401
    assert client.get("/api/v1/inventory/stock", params=params, headers=as_user(role="customer")).status_code == 403


def test_a_seller_sets_their_stock(client, add_stock, stock):
    seller = uuid.uuid4()
    lamp = add_stock(on_hand=5, reserved=2, seller_id=seller)

    response = client.put(f"/api/v1/inventory/stock/{lamp}", json={"on_hand": 12}, headers=as_user(seller))

    assert response.status_code == 200
    assert response.json()["available"] == 10
    assert stock(lamp) == (12, 2)


def test_stock_cannot_go_below_what_is_held_in_checkouts(client, add_stock, stock):
    seller = uuid.uuid4()
    lamp = add_stock(on_hand=5, reserved=2, seller_id=seller)

    response = client.put(f"/api/v1/inventory/stock/{lamp}", json={"on_hand": 1}, headers=as_user(seller))

    assert response.status_code == 409
    assert response.json()["code"] == "below_held"
    assert response.json()["reserved"] == 2
    assert stock(lamp) == (5, 2)


def test_a_seller_cannot_touch_another_sellers_stock(client, add_stock, stock):
    lamp = add_stock(on_hand=5)

    response = client.put(f"/api/v1/inventory/stock/{lamp}", json={"on_hand": 0}, headers=as_user())

    assert response.status_code == 404
    assert stock(lamp) == (5, 0)


def test_an_admin_can_set_any_stock(client, add_stock, stock):
    lamp = add_stock(on_hand=5)

    assert client.put(f"/api/v1/inventory/stock/{lamp}", json={"on_hand": 8},
                      headers=as_user(role="admin")).status_code == 200
    assert stock(lamp) == (8, 0)


def test_a_brand_new_option_asks_to_try_again(client):
    response = client.put(f"/api/v1/inventory/stock/{uuid.uuid4()}", json={"on_hand": 3}, headers=as_user())

    assert response.status_code == 404
    assert response.json()["code"] == "not_ready"


def test_stock_must_be_a_sensible_number(client, add_stock):
    seller = uuid.uuid4()
    lamp = add_stock(on_hand=5, seller_id=seller)

    for bad in (-1, 1_000_001, "lots"):
        assert client.put(f"/api/v1/inventory/stock/{lamp}", json={"on_hand": bad},
                          headers=as_user(seller)).status_code == 422

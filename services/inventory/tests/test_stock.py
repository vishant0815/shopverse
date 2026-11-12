import threading
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import StockItem


def lines(*pairs):
    return [{"variant_id": str(variant), "quantity": quantity} for variant, quantity in pairs]


# Catalogue events ----------------------------------------------------------------------

def variant_data(variant_id, seller_id, sku="LAMP-1", active=True):
    return {"variant_id": str(variant_id), "product_id": str(uuid.uuid4()), "seller_id": str(seller_id),
            "sku": sku, "active": active}


def test_a_new_variant_starts_with_no_stock(send, sessions):
    variant, seller = uuid.uuid4(), uuid.uuid4()

    send("VariantUpserted", variant_data(variant, seller), topic="catalog.variants")

    with sessions() as db:
        item = db.get(StockItem, variant)
        assert (item.on_hand, item.reserved, item.seller_id, item.sku, item.active) == (0, 0, seller, "LAMP-1", True)


def test_catalogue_updates_never_touch_stock(send, sessions):
    variant, seller = uuid.uuid4(), uuid.uuid4()
    send("VariantUpserted", variant_data(variant, seller), topic="catalog.variants")
    with sessions() as db:
        db.get(StockItem, variant).on_hand = 9
        db.commit()

    send("VariantUpserted", variant_data(variant, seller, sku="LAMP-2"), topic="catalog.variants")

    with sessions() as db:
        item = db.get(StockItem, variant)
        assert (item.on_hand, item.sku) == (9, "LAMP-2")


def test_demo_mode_gives_new_variants_some_stock(send, sessions, monkeypatch):
    from app.config import get_settings
    from app.stock import demo_quantity

    monkeypatch.setattr(get_settings(), "demo_stock", True)
    variant = uuid.uuid4()

    send("VariantUpserted", variant_data(variant, uuid.uuid4()), topic="catalog.variants")

    with sessions() as db:
        assert db.get(StockItem, variant).on_hand == demo_quantity(variant)


def test_demo_quantities_include_sold_out_and_low_stock():
    from app.stock import demo_quantity

    quantities = [demo_quantity(uuid.uuid4()) for _ in range(2000)]
    assert 0 in quantities
    assert any(1 <= q <= 4 for q in quantities)
    assert max(quantities) <= 40


def test_a_removed_variant_can_no_longer_be_reserved(send, add_stock, outbox):
    variant = add_stock(on_hand=5)
    send("VariantRemoved", {"variant_id": str(variant)}, topic="catalog.variants")

    send("ReserveStock", {"order_number": "SV-1", "lines": lines((variant, 1))})

    assert outbox()[-1] == ("StockRejected", {"order_number": "SV-1", "unavailable": [
        {"variant_id": str(variant), "requested": 1, "available": 0}]})


# Reserving -----------------------------------------------------------------------------

def test_reserving_holds_the_items(send, add_stock, stock, outbox):
    lamp, chair = add_stock(on_hand=5), add_stock(on_hand=2)

    assert send("ReserveStock", {"order_number": "SV-1", "lines": lines((lamp, 2), (chair, 2))}) == "handled"

    assert stock(lamp) == (5, 2)
    assert stock(chair) == (2, 2)
    kind, data = outbox()[-1]
    assert kind == "StockReserved"
    assert data["order_number"] == "SV-1"
    assert sorted(line["quantity"] for line in data["lines"]) == [2, 2]


def test_two_lines_for_the_same_variant_are_added_together(send, add_stock, stock, outbox):
    lamp = add_stock(on_hand=3)

    send("ReserveStock", {"order_number": "SV-1", "lines": lines((lamp, 2), (lamp, 2))})

    assert stock(lamp) == (3, 0)
    assert outbox()[-1][0] == "StockRejected"


def test_not_enough_stock_holds_nothing_at_all(send, add_stock, stock, outbox):
    lamp, chair = add_stock(on_hand=5), add_stock(on_hand=1, reserved=1)

    send("ReserveStock", {"order_number": "SV-1", "lines": lines((lamp, 2), (chair, 1))})

    assert stock(lamp) == (5, 0)  # all or nothing
    assert outbox()[-1] == ("StockRejected", {"order_number": "SV-1", "unavailable": [
        {"variant_id": str(chair), "requested": 1, "available": 0}]})


def test_unknown_variants_are_unavailable(send, outbox):
    ghost = uuid.uuid4()

    send("ReserveStock", {"order_number": "SV-1", "lines": lines((ghost, 1))})

    assert outbox()[-1][1]["unavailable"] == [{"variant_id": str(ghost), "requested": 1, "available": 0}]


def test_a_repeated_reserve_command_gives_the_same_answer_without_holding_twice(send, add_stock, stock, outbox):
    lamp = add_stock(on_hand=5)
    command = {"order_number": "SV-1", "lines": lines((lamp, 2))}

    send("ReserveStock", command)
    send("ReserveStock", command)  # a new message id: the orchestrator sent it again

    assert stock(lamp) == (5, 2)
    assert [kind for kind, _ in outbox()] == ["StockReserved", "StockReserved"]


def test_the_same_message_twice_is_handled_once(send, add_stock, stock, outbox):
    lamp = add_stock(on_hand=5)
    message_id = uuid.uuid4()
    command = {"order_number": "SV-1", "lines": lines((lamp, 2))}

    assert send("ReserveStock", command, message_id=message_id) == "handled"
    assert send("ReserveStock", command, message_id=message_id) == "duplicate"

    assert stock(lamp) == (5, 2)
    assert len(outbox()) == 1


def test_racing_checkouts_never_oversell(sessions, add_stock, stock, outbox):
    """Twelve checkouts at once for the last 3 lamps: exactly 3 get one."""
    import json

    from app.messaging import process
    from app.stock import HANDLERS
    from tests.conftest import envelope

    lamp = add_stock(on_hand=3)
    barrier = threading.Barrier(12)
    errors = []

    def checkout(n):
        raw = json.dumps(envelope("ReserveStock", {"order_number": f"SV-{n}", "lines": lines((lamp, 1))})).encode()
        barrier.wait()
        try:
            process(sessions, HANDLERS, "inventory.commands", raw)
        except Exception as exc:  # pragma: no cover - the test fails below if this happens
            errors.append(exc)

    threads = [threading.Thread(target=checkout, args=(n,)) for n in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert stock(lamp) == (3, 3)
    kinds = [kind for kind, _ in outbox()]
    assert kinds.count("StockReserved") == 3
    assert kinds.count("StockRejected") == 9


def test_the_database_refuses_to_hold_more_than_is_on_the_shelf(sessions, add_stock):
    lamp = add_stock(on_hand=2)
    with sessions() as db:
        db.get(StockItem, lamp).reserved = 3
        with pytest.raises(IntegrityError):
            db.commit()


# Committing and releasing --------------------------------------------------------------

def test_paying_turns_the_hold_into_a_sale(send, add_stock, stock, outbox):
    lamp = add_stock(on_hand=5)
    send("ReserveStock", {"order_number": "SV-1", "lines": lines((lamp, 2))})

    send("CommitStock", {"order_number": "SV-1"})

    assert stock(lamp) == (3, 0)
    assert outbox()[-1] == ("StockCommitted", {"order_number": "SV-1"})


def test_committing_twice_changes_nothing(send, add_stock, stock):
    lamp = add_stock(on_hand=5)
    send("ReserveStock", {"order_number": "SV-1", "lines": lines((lamp, 2))})
    send("CommitStock", {"order_number": "SV-1"})

    send("CommitStock", {"order_number": "SV-1"})

    assert stock(lamp) == (3, 0)


def test_releasing_a_hold_puts_items_back_on_sale(send, add_stock, stock, outbox):
    lamp = add_stock(on_hand=5)
    send("ReserveStock", {"order_number": "SV-1", "lines": lines((lamp, 2))})

    send("ReleaseStock", {"order_number": "SV-1"})

    assert stock(lamp) == (5, 0)
    assert outbox()[-1] == ("StockReleased", {"order_number": "SV-1"})


def test_releasing_a_sale_puts_items_back_on_the_shelf(send, add_stock, stock):
    lamp = add_stock(on_hand=5)
    send("ReserveStock", {"order_number": "SV-1", "lines": lines((lamp, 2))})
    send("CommitStock", {"order_number": "SV-1"})

    send("ReleaseStock", {"order_number": "SV-1"})

    assert stock(lamp) == (5, 0)


def test_releasing_twice_changes_nothing(send, add_stock, stock):
    lamp = add_stock(on_hand=5)
    send("ReserveStock", {"order_number": "SV-1", "lines": lines((lamp, 2))})
    send("ReleaseStock", {"order_number": "SV-1"})

    send("ReleaseStock", {"order_number": "SV-1"})

    assert stock(lamp) == (5, 0)


def test_releasing_something_never_held_still_answers(send, add_stock, stock, outbox):
    lamp = add_stock(on_hand=1)
    send("ReserveStock", {"order_number": "SV-1", "lines": lines((lamp, 5))})  # rejected

    send("ReleaseStock", {"order_number": "SV-1"})
    send("ReleaseStock", {"order_number": "SV-404"})

    assert stock(lamp) == (1, 0)
    assert [kind for kind, _ in outbox()][-2:] == ["StockReleased", "StockReleased"]


def test_a_released_order_cannot_then_be_committed(send, add_stock, stock):
    lamp = add_stock(on_hand=5)
    send("ReserveStock", {"order_number": "SV-1", "lines": lines((lamp, 2))})
    send("ReleaseStock", {"order_number": "SV-1"})

    send("CommitStock", {"order_number": "SV-1"})

    assert stock(lamp) == (5, 0)

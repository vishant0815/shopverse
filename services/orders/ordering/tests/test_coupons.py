import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from ordering import coupons
from ordering.models import Cart, Coupon, Order
from ordering.pricing import totals_for

ADMIN_COUPONS = "/api/v1/admin/coupons/"
CART_COUPON = "/api/v1/cart/coupon/"
CHECKOUT = "/api/v1/checkout/"


def make_coupon(**overrides):
    fields = {"code": "WELCOME10", "kind": Coupon.Kind.PERCENT, "value": Decimal("10")}
    fields.update(overrides)
    return Coupon.objects.create(**fields)


def make_order(code, status=Order.Status.PAID, user_id=None):
    """A basket of £64.00 with a 10% code taken off: £57.60 to pay."""
    return Order.objects.create(
        user_id=user_id or uuid.uuid4(),
        status=status,
        subtotal=Decimal("64.00"),
        discount_amount=Decimal("6.40"),
        total=Decimal("57.60"),
        shipping_address={"line1": "1 High Street"},
        coupon_code=code,
    )


def add_to_cart(client, catalogue, price="32.00", quantity=1):
    variant_id = catalogue.add(price=price)
    response = client.post("/api/v1/cart/items/", {"variant_id": variant_id, "quantity": quantity}, format="json")
    assert response.status_code in (200, 201)
    return variant_id


def apply(client, code):
    return client.put(CART_COUPON, {"code": code}, format="json")


def checkout(client, address, expected_total=None):
    body = {"shipping_address": address}
    if expected_total is not None:
        body["expected_total"] = str(expected_total)
    return client.post(CHECKOUT, body, format="json")


def line(amount):
    return {"line_total": Decimal(amount)}


class TestDiscountMaths:
    def test_percentage_is_rounded_to_the_penny(self):
        coupon = Coupon(kind=Coupon.Kind.PERCENT, value=Decimal("12.5"))
        assert coupons.discount_for(coupon, Decimal("10.01")) == Decimal("1.25")

    def test_percentage_rounds_half_up(self):
        coupon = Coupon(kind=Coupon.Kind.PERCENT, value=Decimal("10"))
        assert coupons.discount_for(coupon, Decimal("0.05")) == Decimal("0.01")

    def test_fixed_amount_is_taken_off_a_larger_basket(self):
        coupon = Coupon(kind=Coupon.Kind.FIXED, value=Decimal("5"))
        assert coupons.discount_for(coupon, Decimal("40.00")) == Decimal("5.00")

    def test_fixed_amount_never_takes_more_than_the_subtotal(self):
        coupon = Coupon(kind=Coupon.Kind.FIXED, value=Decimal("5"))
        assert coupons.discount_for(coupon, Decimal("3.00")) == Decimal("3.00")


class TestTotalsWithDiscount:
    def test_discount_comes_off_the_subtotal(self):
        totals = totals_for([line("32.00"), line("32.00")], Decimal("6.40"))
        assert totals == {
            "subtotal": Decimal("64.00"),
            "discount_amount": Decimal("6.40"),
            "shipping_fee": Decimal("0.00"),
            "total": Decimal("57.60"),
        }

    def test_shipping_is_judged_before_the_discount(self):
        # £64 qualifies for free delivery. The £6.40 off must not bring a shipping fee back.
        totals = totals_for([line("64.00")], Decimal("6.40"))
        assert totals["shipping_fee"] == Decimal("0.00")
        assert totals["total"] == Decimal("57.60")

    def test_a_small_basket_still_pays_shipping_after_the_discount(self):
        totals = totals_for([line("30.00")], Decimal("5.00"))
        assert totals["shipping_fee"] == Decimal("4.99")
        assert totals["total"] == Decimal("29.99")


@pytest.mark.django_db
class TestCouponRules:
    def refusal(self, coupon, subtotal=Decimal("64.00"), user_id=None, now=None):
        with pytest.raises(coupons.CouponError) as error:
            coupons.check(coupon, subtotal, user_id or uuid.uuid4(), now)
        return error.value.code

    def test_a_working_code_passes(self):
        coupons.check(make_coupon(), Decimal("64.00"), uuid.uuid4())

    def test_an_inactive_code_is_refused(self):
        assert self.refusal(make_coupon(is_active=False)) == "coupon_inactive"

    def test_a_code_is_refused_before_it_starts(self):
        coupon = make_coupon(starts_at=timezone.now() + timedelta(days=1))
        assert self.refusal(coupon) == "coupon_not_started"

    def test_a_code_is_refused_once_it_has_ended(self):
        coupon = make_coupon(starts_at=timezone.now() - timedelta(days=2), ends_at=timezone.now() - timedelta(days=1))
        assert self.refusal(coupon) == "coupon_expired"

    def test_the_minimum_is_checked_before_the_discount(self):
        coupon = make_coupon(min_subtotal=Decimal("50.00"))
        assert self.refusal(coupon, subtotal=Decimal("49.99")) == "coupon_min_not_met"
        coupons.check(coupon, Decimal("50.00"), uuid.uuid4())

    def test_a_code_is_used_up_when_live_orders_reach_the_limit(self):
        coupon = make_coupon(usage_limit=1)
        make_order("WELCOME10")
        assert self.refusal(coupon) == "coupon_used_up"

    def test_cancelled_orders_do_not_use_up_a_code(self):
        coupon = make_coupon(usage_limit=1)
        make_order("WELCOME10", status=Order.Status.CANCELLED)
        coupons.check(coupon, Decimal("64.00"), uuid.uuid4())

    def test_one_customer_can_be_limited_while_others_still_use_the_code(self):
        coupon = make_coupon(per_customer_limit=1)
        shopper = uuid.uuid4()
        make_order("WELCOME10", user_id=shopper)
        assert self.refusal(coupon, user_id=shopper) == "coupon_already_used"
        coupons.check(coupon, Decimal("64.00"), uuid.uuid4())


@pytest.mark.django_db
class TestAdminCoupons:
    def payload(self, **overrides):
        body = {"code": "welcome10", "kind": "percent", "value": "10.00", "min_subtotal": "20.00", "per_customer_limit": 1}
        body.update(overrides)
        return body

    def test_an_admin_creates_a_coupon_with_its_code_in_capitals(self, admin):
        response = admin.post(ADMIN_COUPONS, self.payload(code=" welcome10 "), format="json")
        assert response.status_code == 201
        assert response.data["code"] == "WELCOME10"
        assert response.data["used_count"] == 0

    def test_only_admins_manage_coupons(self, customer, anon):
        assert customer.get(ADMIN_COUPONS).status_code == 403
        assert customer.post(ADMIN_COUPONS, self.payload(), format="json").status_code == 403
        assert anon.get(ADMIN_COUPONS).status_code == 401

    def test_a_percentage_must_be_between_1_and_100(self, admin):
        response = admin.post(ADMIN_COUPONS, self.payload(value="150.00"), format="json")
        assert response.status_code == 400
        assert "value" in response.data

    def test_a_fixed_amount_must_be_more_than_zero(self, admin):
        response = admin.post(ADMIN_COUPONS, self.payload(kind="fixed", value="0.00"), format="json")
        assert response.status_code == 400
        assert "value" in response.data

    def test_codes_are_unique_whatever_the_case(self, admin):
        assert admin.post(ADMIN_COUPONS, self.payload(), format="json").status_code == 201
        response = admin.post(ADMIN_COUPONS, self.payload(code="Welcome10"), format="json")
        assert response.status_code == 400
        assert "code" in response.data

    def test_the_end_must_be_after_the_start(self, admin):
        now = timezone.now()
        response = admin.post(
            ADMIN_COUPONS,
            self.payload(starts_at=now.isoformat(), ends_at=(now - timedelta(days=1)).isoformat()),
            format="json",
        )
        assert response.status_code == 400
        assert "ends_at" in response.data

    def test_a_code_cannot_be_renamed(self, admin):
        admin.post(ADMIN_COUPONS, self.payload(), format="json")
        response = admin.patch(f"{ADMIN_COUPONS}WELCOME10/", {"code": "NEWCODE"}, format="json")
        assert response.status_code == 400
        assert "code" in response.data

    def test_an_admin_can_switch_a_code_off(self, admin, customer, catalogue):
        admin.post(ADMIN_COUPONS, self.payload(min_subtotal="0.00"), format="json")
        add_to_cart(customer, catalogue)
        admin.patch(f"{ADMIN_COUPONS}WELCOME10/", {"is_active": False}, format="json")
        response = apply(customer, "WELCOME10")
        assert response.status_code == 400
        assert response.data["code"] == "coupon_inactive"

    def test_used_count_counts_live_orders_only(self, admin):
        admin.post(ADMIN_COUPONS, self.payload(), format="json")
        make_order("WELCOME10")
        make_order("WELCOME10", status=Order.Status.CANCELLED)
        response = admin.get(f"{ADMIN_COUPONS}welcome10/")
        assert response.status_code == 200
        assert response.data["used_count"] == 1


@pytest.mark.django_db
class TestApplyingACode:
    def test_a_valid_code_takes_the_discount_off_the_basket(self, customer, catalogue):
        make_coupon()
        add_to_cart(customer, catalogue, "32.00", quantity=2)
        response = apply(customer, "welcome10")
        assert response.status_code == 200
        assert response.data["coupon"] == {
            "code": "WELCOME10", "valid": True, "reason": "", "message": "", "kind": "percent", "value": "10.00",
        }
        assert response.data["discount_amount"] == "6.40"
        assert response.data["shipping_fee"] == "0.00"
        assert response.data["total"] == "57.60"

    def test_an_unknown_code_is_refused(self, customer, catalogue):
        add_to_cart(customer, catalogue)
        response = apply(customer, "NOPE")
        assert response.status_code == 400
        assert response.data["code"] == "coupon_not_found"

    def test_a_basket_below_the_minimum_is_refused(self, customer, catalogue):
        make_coupon(min_subtotal=Decimal("50.00"))
        add_to_cart(customer, catalogue, "30.00")
        response = apply(customer, "WELCOME10")
        assert response.status_code == 400
        assert response.data["code"] == "coupon_min_not_met"
        assert "£50.00" in response.data["detail"]

    def test_an_empty_basket_cannot_take_a_code(self, customer):
        make_coupon()
        response = apply(customer, "WELCOME10")
        assert response.status_code == 400
        assert response.data["code"] == "cart_empty"

    def test_removing_the_code_restores_the_full_total(self, customer, catalogue):
        make_coupon()
        add_to_cart(customer, catalogue, "32.00", quantity=2)
        apply(customer, "WELCOME10")
        response = customer.delete(CART_COUPON)
        assert response.status_code == 200
        assert response.data["coupon"] is None
        assert response.data["total"] == "64.00"

    def test_a_code_that_expires_after_it_was_applied_gives_nothing_off(self, customer, catalogue):
        coupon = make_coupon()
        add_to_cart(customer, catalogue, "32.00", quantity=2)
        apply(customer, "WELCOME10")
        coupon.ends_at = timezone.now() - timedelta(minutes=1)
        coupon.save()
        response = customer.get("/api/v1/cart/")
        assert response.data["coupon"]["valid"] is False
        assert response.data["coupon"]["reason"] == "coupon_expired"
        assert response.data["discount_amount"] == "0.00"
        assert response.data["total"] == "64.00"

    def test_a_fixed_amount_cannot_take_more_than_the_basket(self, customer, catalogue):
        make_coupon(kind=Coupon.Kind.FIXED, value=Decimal("100"))
        add_to_cart(customer, catalogue, "32.00", quantity=2)
        response = apply(customer, "WELCOME10")
        assert response.data["discount_amount"] == "64.00"
        assert response.data["total"] == "0.00"

    def test_free_shipping_survives_a_discount_that_drops_the_basket_below_the_threshold(self, customer, catalogue):
        make_coupon(value=Decimal("20"))
        add_to_cart(customer, catalogue, "32.00", quantity=2)
        response = apply(customer, "WELCOME10")
        assert response.data["discount_amount"] == "12.80"
        assert response.data["shipping_fee"] == "0.00"
        assert response.data["total"] == "51.20"


@pytest.mark.django_db
class TestCheckoutWithACode:
    def test_the_order_records_the_code_and_the_discount(self, customer, catalogue, address):
        make_coupon()
        add_to_cart(customer, catalogue, "32.00", quantity=2)
        apply(customer, "WELCOME10")
        response = checkout(customer, address)
        assert response.status_code == 201
        order = Order.objects.get(number=response.data["number"])
        assert order.coupon_code == "WELCOME10"
        assert order.discount_amount == Decimal("6.40")
        assert order.total == Decimal("57.60")
        assert Cart.objects.get(user_id=customer.user_id).coupon_code == ""

    def test_the_expected_total_is_checked_with_the_discount_in_it(self, customer, catalogue, address):
        make_coupon()
        add_to_cart(customer, catalogue, "32.00", quantity=2)
        apply(customer, "WELCOME10")
        stale = checkout(customer, address, expected_total="64.00")
        assert stale.status_code == 409
        assert stale.data["code"] == "price_changed"
        assert checkout(customer, address, expected_total="57.60").status_code == 201

    def test_an_expired_code_stops_checkout_and_creates_no_order(self, customer, catalogue, address):
        coupon = make_coupon()
        add_to_cart(customer, catalogue, "32.00", quantity=2)
        apply(customer, "WELCOME10")
        coupon.ends_at = timezone.now() - timedelta(minutes=1)
        coupon.save()
        response = checkout(customer, address)
        assert response.status_code == 409
        assert response.data["code"] == "coupon_invalid"
        assert response.data["reason"] == "coupon_expired"
        assert Order.objects.count() == 0

    def test_a_code_used_up_by_someone_else_stops_the_second_checkout(self, customer, other_customer, catalogue, address):
        make_coupon(usage_limit=1)
        add_to_cart(customer, catalogue, "32.00", quantity=2)
        apply(customer, "WELCOME10")
        add_to_cart(other_customer, catalogue, "32.00", quantity=2)
        apply(other_customer, "WELCOME10")
        assert checkout(other_customer, address).status_code == 201
        response = checkout(customer, address)
        assert response.status_code == 409
        assert response.data["reason"] == "coupon_used_up"
        assert Order.objects.count() == 1

    def test_cancelling_an_order_gives_its_use_back(self, customer, other_customer, catalogue, address):
        make_coupon(usage_limit=1)
        add_to_cart(customer, catalogue, "32.00", quantity=2)
        apply(customer, "WELCOME10")
        number = checkout(customer, address).data["number"]
        cancel = customer.post(f"/api/v1/orders/{number}/cancel/", {"reason": "changed my mind"}, format="json")
        assert cancel.status_code == 200
        add_to_cart(other_customer, catalogue, "32.00", quantity=2)
        response = apply(other_customer, "WELCOME10")
        assert response.status_code == 200

    def test_a_customer_cannot_use_a_limited_code_twice(self, customer, catalogue, address):
        make_coupon(per_customer_limit=1)
        add_to_cart(customer, catalogue, "32.00", quantity=2)
        apply(customer, "WELCOME10")
        assert checkout(customer, address).status_code == 201
        add_to_cart(customer, catalogue, "32.00", quantity=2)
        response = apply(customer, "WELCOME10")
        assert response.status_code == 400
        assert response.data["code"] == "coupon_already_used"

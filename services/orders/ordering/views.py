from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import catalog
from .checkout import CheckoutError, place_order
from .models import Cart, CartItem, Order, OrderItem
from .permissions import IsAdmin, IsCustomer, IsSeller, IsService, user_id_of
from .pricing import price_lines, totals_for
from .serializers import (
    AddToCartSerializer,
    CancelSerializer,
    CheckoutSerializer,
    OrderDetailSerializer,
    OrderListSerializer,
    PaymentConfirmedSerializer,
    SellerOrderItemSerializer,
    TransitionSerializer,
    UpdateCartItemSerializer,
)


def get_cart(request, lock=False):
    cart, _ = Cart.objects.get_or_create(user_id=user_id_of(request))
    if lock:
        cart = Cart.objects.select_for_update().get(pk=cart.pk)
    return cart


def cart_response(cart, status_code=status.HTTP_200_OK):
    """The cart with live prices. If the catalogue is down, the cart still loads,
    just without prices, so the customer isn't locked out of their own cart."""
    items = list(cart.items.all())
    try:
        variants = catalog.lookup_variants([i.variant_id for i in items])
    except catalog.CatalogUnavailable:
        return Response(
            {
                "items": [{"variant_id": str(i.variant_id), "quantity": i.quantity} for i in items],
                "prices_available": False,
            },
            status=status_code,
        )

    lines, unavailable = price_lines(items, variants)
    data = {
        "items": [
            {
                "variant_id": str(line["item"].variant_id),
                "quantity": line["item"].quantity,
                "sku": line["info"]["sku"],
                "product_name": line["info"]["product_name"],
                "product_slug": line["info"]["product_slug"],
                "colour": line["info"].get("colour", ""),
                "size": line["info"].get("size", ""),
                "thumbnail": line["info"].get("thumbnail"),
                "unit_price": str(line["unit_price"]),
                "line_total": str(line["line_total"]),
            }
            for line in lines
        ],
        "unavailable_variant_ids": unavailable,
        "prices_available": True,
        "currency": settings.CURRENCY,
        **{key: str(value) for key, value in totals_for(lines).items()},
    }
    return Response(data, status=status_code)


class CartView(APIView):
    permission_classes = [IsCustomer]

    def get(self, request):
        return cart_response(get_cart(request))

    def delete(self, request):
        get_cart(request).items.all().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CartItemsView(APIView):
    permission_classes = [IsCustomer]

    def post(self, request):
        serializer = AddToCartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        variant_id = serializer.validated_data["variant_id"]
        quantity = serializer.validated_data["quantity"]

        try:
            available = catalog.lookup_variants([variant_id])
        except catalog.CatalogUnavailable:
            return Response({"detail": "The catalogue is unavailable. Please try again."}, status=503)
        if str(variant_id) not in available:
            return Response({"detail": "This item isn't available."}, status=status.HTTP_404_NOT_FOUND)

        with transaction.atomic():
            cart = get_cart(request, lock=True)  # lock so two quick clicks add up correctly
            item = cart.items.filter(variant_id=variant_id).first()
            new_quantity = (item.quantity if item else 0) + quantity
            if new_quantity > settings.MAX_QUANTITY_PER_ITEM:
                return Response(
                    {"detail": f"You can buy at most {settings.MAX_QUANTITY_PER_ITEM} of one item."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if item is None and cart.items.count() >= settings.MAX_CART_ITEMS:
                return Response(
                    {"detail": f"Your cart can hold at most {settings.MAX_CART_ITEMS} different items."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if item:
                item.quantity = new_quantity
                item.save(update_fields=["quantity"])
            else:
                CartItem.objects.create(cart=cart, variant_id=variant_id, quantity=quantity)
            cart.save(update_fields=["updated_at"])

        return cart_response(cart, status.HTTP_201_CREATED)


class CartItemDetailView(APIView):
    permission_classes = [IsCustomer]

    def get_item(self, request, variant_id):
        return get_object_or_404(CartItem, cart__user_id=user_id_of(request), variant_id=variant_id)

    def patch(self, request, variant_id):
        serializer = UpdateCartItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = self.get_item(request, variant_id)
        item.quantity = serializer.validated_data["quantity"]
        item.save(update_fields=["quantity"])
        return cart_response(item.cart)

    def delete(self, request, variant_id):
        item = self.get_item(request, variant_id)
        cart = item.cart
        item.delete()
        return cart_response(cart)


class CheckoutView(APIView):
    """POST with an Idempotency-Key header. Sending the same key again returns the
    same order instead of creating a second one."""

    permission_classes = [IsCustomer]

    def post(self, request):
        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        key = request.headers.get("Idempotency-Key", "").strip()
        if len(key) > 100:
            return Response({"detail": "Idempotency-Key must be at most 100 characters."}, status=400)

        try:
            order, created = place_order(
                user_id=user_id_of(request),
                shipping_address=serializer.validated_data["shipping_address"],
                idempotency_key=key,
                expected_total=serializer.validated_data.get("expected_total"),
            )
        except CheckoutError as error:
            return Response(error.as_response_data(), status=error.status)

        order = Order.objects.prefetch_related("items", "history").get(pk=order.pk)
        return Response(
            OrderDetailSerializer(order).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class MyOrdersView(generics.ListAPIView):
    permission_classes = [IsCustomer]
    serializer_class = OrderListSerializer

    def get_queryset(self):
        return Order.objects.filter(user_id=user_id_of(self.request)).prefetch_related("items")


class MyOrderDetailView(generics.RetrieveAPIView):
    permission_classes = [IsCustomer]
    serializer_class = OrderDetailSerializer
    lookup_field = "number"

    def get_queryset(self):
        # Ownership: another customer's order number returns 404.
        return Order.objects.filter(user_id=user_id_of(self.request)).prefetch_related("items", "history")


class CancelOrderView(APIView):
    permission_classes = [IsCustomer]

    def post(self, request, number):
        serializer = CancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            order = get_object_or_404(
                Order.objects.select_for_update(), user_id=user_id_of(request), number=number
            )
            if order.status not in Order.CUSTOMER_CANCELLABLE:
                return Response(
                    {"detail": f"An order that is {order.get_status_display().lower()} can't be cancelled."},
                    status=status.HTTP_409_CONFLICT,
                )
            order.move_to(Order.Status.CANCELLED, changed_by=user_id_of(request),
                          note=serializer.validated_data["reason"] or "Cancelled by customer")
        order = Order.objects.prefetch_related("items", "history").get(pk=order.pk)
        return Response(OrderDetailSerializer(order).data)


class SellerSalesView(generics.ListAPIView):
    """A seller's own lines across all orders. Other sellers' items and buyer details stay hidden."""

    permission_classes = [IsSeller]
    serializer_class = SellerOrderItemSerializer

    def get_queryset(self):
        queryset = OrderItem.objects.filter(seller_id=user_id_of(self.request)).select_related("order")
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(order__status=status_filter)
        return queryset.order_by("-order__created_at", "id")


class AdminOrderListView(generics.ListAPIView):
    permission_classes = [IsAdmin]
    serializer_class = OrderListSerializer

    def get_queryset(self):
        queryset = Order.objects.prefetch_related("items")
        status_filter = self.request.query_params.get("status")
        return queryset.filter(status=status_filter) if status_filter else queryset


class AdminOrderDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAdmin]
    serializer_class = OrderDetailSerializer
    lookup_field = "number"
    queryset = Order.objects.prefetch_related("items", "history")


class AdminTransitionView(APIView):
    """Move an order along its lifecycle. Only moves listed in Order.TRANSITIONS are allowed.
    Once the payment service exists, it will mark orders as paid instead of an admin."""

    permission_classes = [IsAdmin]

    def post(self, request, number):
        serializer = TransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data["status"]
        with transaction.atomic():
            order = get_object_or_404(Order.objects.select_for_update(), number=number)
            if not order.can_move_to(new_status):
                allowed = sorted(order.TRANSITIONS[order.status])
                return Response(
                    {"detail": f"Can't move an order from {order.status} to {new_status}.", "allowed": allowed},
                    status=status.HTTP_409_CONFLICT,
                )
            order.move_to(new_status, changed_by=user_id_of(request), note=serializer.validated_data["note"])
        order = Order.objects.prefetch_related("items", "history").get(pk=order.pk)
        return Response(OrderDetailSerializer(order).data)


class PaymentConfirmedView(APIView):
    """Called by the payments service once the payment provider confirms a payment.

    Safe to call more than once: an order that is already paid simply returns 200.
    The amount is checked against the order total, so a wrong amount can never mark an order paid.
    """

    permission_classes = [IsService]

    def post(self, request, number):
        serializer = PaymentConfirmedSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        with transaction.atomic():
            order = get_object_or_404(Order.objects.select_for_update(), number=number)
            if data["amount"] != order.total or data["currency"].upper() != order.currency:
                return Response(
                    {"code": "amount_mismatch", "detail": "Payment amount doesn't match the order total.",
                     "order_total": str(order.total), "currency": order.currency},
                    status=status.HTTP_409_CONFLICT,
                )
            if order.status == Order.Status.PENDING_PAYMENT:
                order.move_to(Order.Status.PAID, changed_by=None, note=f"Payment {data['payment_id']} confirmed")
            elif order.status == Order.Status.CANCELLED:
                return Response(
                    {"code": "order_cancelled", "detail": "The order was cancelled before payment completed."},
                    status=status.HTTP_409_CONFLICT,
                )
            # paid, shipped or delivered: already handled, nothing to do.
        return Response({"number": order.number, "status": order.status})

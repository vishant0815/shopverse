from django.conf import settings
from rest_framework import serializers

from .models import CheckoutSaga, Order, OrderItem, OrderStatusHistory


class AddToCartSerializer(serializers.Serializer):
    variant_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1, default=1)


class UpdateCartItemSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1)

    def validate_quantity(self, value):
        if value > settings.MAX_QUANTITY_PER_ITEM:
            raise serializers.ValidationError(f"You can buy at most {settings.MAX_QUANTITY_PER_ITEM} of one item.")
        return value


class ShippingAddressSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=20)
    line1 = serializers.CharField(max_length=255)
    line2 = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    city = serializers.CharField(max_length=100)
    county = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    postcode = serializers.CharField(max_length=20)
    country = serializers.CharField(max_length=2, default="GB")

    def validate_postcode(self, value):
        return value.strip().upper()

    def validate_country(self, value):
        value = value.strip().upper()
        if len(value) != 2 or not value.isalpha():
            raise serializers.ValidationError("Use a two-letter country code, e.g. GB.")
        return value


class CheckoutSerializer(serializers.Serializer):
    shipping_address = ShippingAddressSerializer()
    # Optional: the total the customer saw. If the real total differs (a price changed
    # since they looked), checkout stops instead of charging a different amount.
    expected_total = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = [
            "variant_id", "product_id", "sku", "product_name", "product_slug",
            "colour", "size", "thumbnail", "unit_price", "quantity", "line_total",
        ]


class StatusHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderStatusHistory
        fields = ["from_status", "to_status", "note", "created_at"]


class OrderListSerializer(serializers.ModelSerializer):
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ["id", "number", "status", "currency", "total", "item_count", "created_at"]

    def get_item_count(self, obj):
        return sum(item.quantity for item in obj.items.all())


class OrderDetailSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    history = StatusHistorySerializer(many=True, read_only=True)
    can_cancel = serializers.SerializerMethodField()
    hold_expires_at = serializers.SerializerMethodField()
    cancellation = serializers.SerializerMethodField()
    refund = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id", "number", "user_id", "status", "currency", "subtotal", "shipping_fee", "total",
            "shipping_address", "items", "history", "can_cancel", "hold_expires_at", "cancellation", "refund",
            "created_at", "updated_at",
        ]

    @staticmethod
    def _saga(obj):
        try:
            return obj.saga
        except CheckoutSaga.DoesNotExist:
            return None

    def get_can_cancel(self, obj):
        return obj.status in Order.CUSTOMER_CANCELLABLE

    def get_hold_expires_at(self, obj):
        """While awaiting payment: when the held items go back on sale."""
        saga = self._saga(obj)
        if saga and obj.status == Order.Status.PENDING_PAYMENT and saga.hold_expires_at:
            return serializers.DateTimeField().to_representation(saga.hold_expires_at)
        return None

    def get_cancellation(self, obj):
        saga = self._saga(obj)
        if obj.status != Order.Status.CANCELLED or not saga or not saga.cancel_code:
            return None
        return {"code": saga.cancel_code, "detail": saga.cancel_detail}

    def get_refund(self, obj):
        saga = self._saga(obj)
        if not saga or not saga.refund_status:
            return None
        return {"status": saga.refund_status, "amount": str(saga.refund_amount) if saga.refund_amount else None}


class TransitionSerializer(serializers.Serializer):
    # Paid isn't here: only a confirmed payment, through the checkout saga, makes an order paid.
    status = serializers.ChoiceField(choices=[
        (s.value, s.label) for s in (Order.Status.SHIPPED, Order.Status.DELIVERED, Order.Status.CANCELLED)
    ])
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class SellerOrderItemSerializer(serializers.ModelSerializer):
    """What a seller sees of a sale: their own lines only, no buyer details."""

    order_number = serializers.CharField(source="order.number")
    order_status = serializers.CharField(source="order.status")
    ordered_at = serializers.DateTimeField(source="order.created_at")

    class Meta:
        model = OrderItem
        fields = [
            "order_number", "order_status", "ordered_at", "sku", "product_name",
            "colour", "size", "unit_price", "quantity", "line_total",
        ]

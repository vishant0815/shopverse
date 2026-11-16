"""Endpoints for the other services. The gateway doesn't route /api/v1/internal/, so only services on the
internal network can reach them."""

import uuid

from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Order, OrderItem


class VerifiedPurchaseView(APIView):
    """Has this customer had a delivered order that contains this product? The products service asks
    before it accepts a review, so a review is only written by someone who really received the product."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        try:
            user_id = uuid.UUID(request.query_params["user_id"])
            product_id = uuid.UUID(request.query_params["product_id"])
        except (KeyError, ValueError):
            return Response({"detail": "user_id and product_id must be UUIDs."}, status=400)
        verified = OrderItem.objects.filter(
            product_id=product_id,
            order__user_id=user_id,
            order__status=Order.Status.DELIVERED,
        ).exists()
        return Response({"verified": verified})

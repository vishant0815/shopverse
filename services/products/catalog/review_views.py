"""Reviews API. Shoppers read a product's reviews and write, edit or see their own; admins hide and show them."""

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from . import reviews
from .models import Product, Review
from .permissions import IsAdmin, user_id_of
from .review_serializers import AdminReviewSerializer, ReviewSerializer


class IsReviewAdmin(IsAdmin):
    message = "Only admins can moderate reviews."


def _product(slug):
    # Only products a shopper can see can be reviewed, so a hidden product's reviews are not reachable either.
    return get_object_or_404(Product.objects.for_shoppers(), slug=slug)


def _not_signed_in(message):
    return Response({"detail": message, "code": "not_signed_in"}, status=401)


def _verification_unavailable():
    return Response(
        {"detail": "Reviews are unavailable right now. Try again shortly.", "code": "verification_unavailable"},
        status=503,
    )


class ProductReviewsView(APIView):
    """GET: the rating summary and the newest visible reviews. POST: write a review."""

    permission_classes = [permissions.AllowAny]

    def get(self, request, slug):
        product = _product(slug)
        visible = product.reviews.filter(status=Review.Status.VISIBLE)[: reviews.LIST_LIMIT]
        return Response({
            "summary": reviews.summary(product),
            "results": ReviewSerializer(visible, many=True).data,
        })

    def post(self, request, slug):
        user_id = user_id_of(request)
        if user_id is None:
            return _not_signed_in("Sign in to write a review.")
        product = _product(slug)
        serializer = ReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            review = reviews.create_review(product, user_id, **serializer.validated_data)
        except reviews.AlreadyReviewed:
            return Response(
                {"detail": "You have already reviewed this product.", "code": "already_reviewed"},
                status=409,
            )
        except reviews.NotVerifiedBuyer:
            return Response(
                {"detail": "Only customers who bought this product can review it.", "code": "not_verified_buyer"},
                status=403,
            )
        except reviews.PurchaseCheckUnavailable:
            return _verification_unavailable()
        return Response(ReviewSerializer(review).data, status=201)


class ProductReviewMineView(APIView):
    """The signed-in customer's own review of a product, and whether they may write one."""

    permission_classes = [permissions.AllowAny]  # checked by hand, so the public product page still loads

    def get(self, request, slug):
        user_id = user_id_of(request)
        if user_id is None:
            return _not_signed_in("Sign in to review products.")
        product = _product(slug)
        review = product.reviews.filter(user_id=user_id).first()
        try:
            # A review exists only because the purchase was verified when it was written.
            verified = True if review else reviews.verified_purchase(user_id, product.pk)
        except reviews.PurchaseCheckUnavailable:
            return _verification_unavailable()
        return Response({
            "review": ReviewSerializer(review).data if review else None,
            "verified": verified,
        })

    def put(self, request, slug):
        user_id = user_id_of(request)
        if user_id is None:
            return _not_signed_in("Sign in to edit your review.")
        product = _product(slug)
        review = product.reviews.filter(user_id=user_id).first()
        if review is None:
            return Response({"detail": "You have not reviewed this product yet.", "code": "no_review"}, status=404)
        serializer = ReviewSerializer(review, data=request.data)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(review, field, value)
        reviews.save_review(review)
        return Response(ReviewSerializer(review).data)


class AdminReviewListView(generics.ListAPIView):
    permission_classes = [IsReviewAdmin]
    serializer_class = AdminReviewSerializer

    def get_queryset(self):
        queryset = Review.objects.select_related("product").order_by("-created_at")
        status_filter = self.request.query_params.get("status")
        if status_filter in Review.Status.values:
            queryset = queryset.filter(status=status_filter)
        return queryset


class AdminReviewDetailView(generics.RetrieveUpdateAPIView):
    """Hide or show a review. Only the status changes."""

    permission_classes = [IsReviewAdmin]
    serializer_class = AdminReviewSerializer
    queryset = Review.objects.select_related("product")
    http_method_names = ["get", "patch", "head", "options"]

    def perform_update(self, serializer):
        with transaction.atomic():
            review = serializer.save()
            reviews.refresh_rating(review.product)

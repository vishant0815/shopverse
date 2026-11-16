from rest_framework import serializers

from . import reviews
from .models import Review


class ReviewSerializer(serializers.ModelSerializer):
    """What a shopper sees of a review, and what they send to write or edit their own."""

    class Meta:
        model = Review
        fields = ["id", "rating", "title", "body", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_rating(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError("Choose a rating from 1 to 5 stars.")
        return value

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Add a title.")
        return value

    def validate_body(self, value):
        value = value.strip()
        if len(value) < reviews.BODY_MIN:
            raise serializers.ValidationError(f"Write at least {reviews.BODY_MIN} characters.")
        return value


class AdminReviewSerializer(serializers.ModelSerializer):
    """For moderation. Only the status can change; the rest is the customer's own words."""

    product_id = serializers.UUIDField(source="product.id", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_slug = serializers.CharField(source="product.slug", read_only=True)

    class Meta:
        model = Review
        fields = [
            "id", "product_id", "product_name", "product_slug", "user_id",
            "rating", "title", "body", "status", "created_at",
        ]
        read_only_fields = [
            "id", "product_id", "product_name", "product_slug", "user_id",
            "rating", "title", "body", "created_at",
        ]

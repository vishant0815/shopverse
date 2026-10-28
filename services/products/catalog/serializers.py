from django.db import transaction
from rest_framework import serializers

from .models import Category, Product, ProductImage, ProductVariant


class CategorySerializer(serializers.ModelSerializer):
    parent = serializers.SlugRelatedField(
        slug_field="slug", queryset=Category.objects.all(), allow_null=True, required=False
    )

    class Meta:
        model = Category
        fields = ["id", "name", "slug", "parent", "description", "position", "is_active"]
        read_only_fields = ["id"]
        extra_kwargs = {"slug": {"required": False}}

    def validate(self, attrs):
        parent = attrs.get("parent")
        if self.instance and parent:
            # A category can't be moved under itself or one of its own children.
            if parent.id in self.instance.descendant_ids():
                raise serializers.ValidationError({"parent": "A category can't be its own ancestor."})
        return attrs


class VariantSerializer(serializers.ModelSerializer):
    discount_percent = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = ["id", "sku", "colour", "size", "price", "compare_at_price", "discount_percent", "is_active"]
        read_only_fields = ["id"]

    def get_discount_percent(self, obj):
        if obj.compare_at_price and obj.compare_at_price > obj.price:
            return round((1 - obj.price / obj.compare_at_price) * 100)
        return 0

    def validate_sku(self, value):
        return value.strip().upper()

    def validate(self, attrs):
        price = attrs.get("price", getattr(self.instance, "price", None))
        compare_at = attrs.get("compare_at_price", getattr(self.instance, "compare_at_price", None))
        if price is not None and compare_at is not None and compare_at < price:
            raise serializers.ValidationError({"compare_at_price": "Must be equal to or higher than the price."})
        return attrs


class ImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["id", "url", "alt_text", "position"]
        read_only_fields = ["id"]


class CategorySummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["name", "slug"]


class ProductListSerializer(serializers.ModelSerializer):
    """Lightweight shape for product grids and search results."""

    category = CategorySummarySerializer(read_only=True)
    min_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    thumbnail = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ["id", "name", "slug", "brand", "category", "min_price", "thumbnail", "seller_id", "status"]

    def get_thumbnail(self, obj):
        images = list(obj.images.all())  # uses prefetched images, no extra query
        return images[0].url if images else None


class ProductDetailSerializer(ProductListSerializer):
    variants = serializers.SerializerMethodField()
    images = ImageSerializer(many=True, read_only=True)

    class Meta(ProductListSerializer.Meta):
        fields = ProductListSerializer.Meta.fields + ["description", "variants", "images", "created_at", "updated_at"]

    def get_variants(self, obj):
        variants = [v for v in obj.variants.all() if v.is_active or self.context.get("show_inactive")]
        return VariantSerializer(variants, many=True).data


class ProductWriteSerializer(serializers.ModelSerializer):
    """Used by sellers. Variants and images can be sent with a new product;
    after that they are managed through their own endpoints."""

    category = serializers.SlugRelatedField(slug_field="slug", queryset=Category.objects.filter(is_active=True))
    variants = VariantSerializer(many=True, required=False)
    images = ImageSerializer(many=True, required=False)

    class Meta:
        model = Product
        fields = ["id", "name", "slug", "brand", "description", "category", "status", "variants", "images"]
        read_only_fields = ["id", "slug"]

    def validate(self, attrs):
        if self.instance is not None and ("variants" in attrs or "images" in attrs):
            raise serializers.ValidationError(
                "Update variants and images through their own endpoints."
            )

        status = attrs.get("status", getattr(self.instance, "status", Product.Status.DRAFT))
        if status == Product.Status.ACTIVE:
            if self.instance is None:
                has_variant = any(v.get("is_active", True) for v in attrs.get("variants", []))
            else:
                has_variant = self.instance.variants.filter(is_active=True).exists()
            if not has_variant:
                raise serializers.ValidationError(
                    {"status": "A product needs at least one active variant before it can be published."}
                )

        variants = attrs.get("variants", [])
        option_pairs = [(v.get("colour", ""), v.get("size", "")) for v in variants]
        if len(option_pairs) != len(set(option_pairs)):
            raise serializers.ValidationError({"variants": "Two variants have the same colour and size."})
        skus = [v["sku"] for v in variants]
        if len(skus) != len(set(skus)):
            raise serializers.ValidationError({"variants": "SKUs must be unique."})
        taken = ProductVariant.objects.filter(sku__in=skus).values_list("sku", flat=True)
        if taken:
            raise serializers.ValidationError({"variants": f"SKU already in use: {', '.join(taken)}"})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        variants = validated_data.pop("variants", [])
        images = validated_data.pop("images", [])
        product = Product.objects.create(**validated_data)
        ProductVariant.objects.bulk_create([ProductVariant(product=product, **v) for v in variants])
        ProductImage.objects.bulk_create([ProductImage(product=product, **i) for i in images])
        return product

    def to_representation(self, instance):
        instance = Product.objects.with_listing_data().get(pk=instance.pk)
        return ProductDetailSerializer(instance, context={**self.context, "show_inactive": True}).data

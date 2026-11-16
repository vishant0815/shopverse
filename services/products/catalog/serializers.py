from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import serializers

from . import events, flash_sales
from .models import Category, FlashSale, FlashSaleItem, Product, ProductImage, ProductVariant


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
        # The slug is made from the name when it isn't given, so check it's free
        # here rather than letting the database reject it.
        if self.instance is None and not attrs.get("slug"):
            slug = slugify(attrs.get("name", ""))[:140]
            if Category.objects.filter(slug=slug).exists():
                raise serializers.ValidationError({"slug": "A category with this name already exists."})
        parent = attrs.get("parent")
        if self.instance and parent:
            # A category can't be moved under itself or one of its own children.
            if parent.id in self.instance.descendant_ids():
                raise serializers.ValidationError({"parent": "A category can't be its own ancestor."})
        return attrs


class VariantSerializer(serializers.ModelSerializer):
    discount_percent = serializers.SerializerMethodField()
    # The sale running on this variant right now, or None. `price` stays the regular price.
    flash_sale = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = [
            "id", "sku", "colour", "size", "price", "compare_at_price", "discount_percent", "is_active", "flash_sale",
        ]
        read_only_fields = ["id"]

    def get_discount_percent(self, obj):
        if obj.compare_at_price and obj.compare_at_price > obj.price:
            return round((1 - obj.price / obj.compare_at_price) * 100)
        return 0

    def get_flash_sale(self, obj):
        item = flash_sales.running_items([obj.id]).get(str(obj.id))
        return flash_sales.flash_sale_payload(item)

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
    compare_at_price = serializers.SerializerMethodField()
    discount_percent = serializers.SerializerMethodField()
    thumbnail = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id", "name", "slug", "brand", "category", "min_price", "compare_at_price",
            "discount_percent", "thumbnail", "seller_id", "status",
        ]

    def _cheapest(self, obj):
        """The active variant whose price is shown on the card (uses prefetched variants)."""
        active = [v for v in obj.variants.all() if v.is_active]
        return min(active, key=lambda v: v.price) if active else None

    def get_compare_at_price(self, obj):
        variant = self._cheapest(obj)
        if variant and variant.compare_at_price and variant.compare_at_price > variant.price:
            return str(variant.compare_at_price)
        return None

    def get_discount_percent(self, obj):
        variant = self._cheapest(obj)
        if variant and variant.compare_at_price and variant.compare_at_price > variant.price:
            return round((1 - variant.price / variant.compare_at_price) * 100)
        return 0

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
        created = ProductVariant.objects.bulk_create([ProductVariant(product=product, **v) for v in variants])
        for variant in created:  # bulk_create skips post_save, so announce these by hand
            events.variant_upserted(variant)
        ProductImage.objects.bulk_create([ProductImage(product=product, **i) for i in images])
        events.announce_product(product.pk)  # the product's own save came before its variants and images
        return product

    def to_representation(self, instance):
        instance = Product.objects.with_listing_data().get(pk=instance.pk)
        return ProductDetailSerializer(instance, context={**self.context, "show_inactive": True}).data


class VariantLookupSerializer(serializers.ModelSerializer):
    """Everything the orders service needs to price and snapshot a cart line."""

    variant_id = serializers.UUIDField(source="id")
    product_id = serializers.UUIDField(source="product.id")
    product_name = serializers.CharField(source="product.name")
    product_slug = serializers.CharField(source="product.slug")
    seller_id = serializers.UUIDField(source="product.seller_id")
    thumbnail = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = [
            "variant_id", "sku", "colour", "size", "price", "compare_at_price",
            "product_id", "product_name", "product_slug", "seller_id", "thumbnail",
        ]

    def to_representation(self, instance):
        # `price` is the price a cart line pays: the sale price while a flash sale runs, else the regular price.
        # `regular_price` is always the regular price, so the basket can show what the sale saves against.
        data = super().to_representation(instance)
        item = self.context.get("sales", {}).get(str(instance.id))
        data["regular_price"] = data["price"]
        data["price"] = f"{item.sale_price:.2f}" if item else data["price"]
        data["flash_sale"] = flash_sales.flash_sale_payload(item)
        return data

    def get_thumbnail(self, obj):
        images = list(obj.product.images.all())
        return images[0].url if images else None


# Flash sales (admin) --------------------------------------------------------------------------

class FlashSaleItemSerializer(serializers.ModelSerializer):
    variant = serializers.PrimaryKeyRelatedField(queryset=ProductVariant.objects.select_related("product"))
    sku = serializers.CharField(source="variant.sku", read_only=True)
    variant_label = serializers.SerializerMethodField()
    regular_price = serializers.DecimalField(source="variant.price", max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = FlashSaleItem
        fields = ["id", "variant", "sku", "variant_label", "regular_price", "sale_price", "quantity_cap"]
        read_only_fields = ["id"]

    def get_variant_label(self, obj):
        return str(obj.variant)


class FlashSaleSerializer(serializers.ModelSerializer):
    """Creating a sale takes its items in one request. A sale's items and window are fixed after that:
    admins switch a sale on or off, which FlashSaleStatusSerializer handles."""

    items = FlashSaleItemSerializer(many=True)

    class Meta:
        model = FlashSale
        fields = ["id", "name", "starts_at", "ends_at", "is_active", "items", "created_at"]
        read_only_fields = ["id", "is_active", "created_at"]

    def validate(self, attrs):
        starts, ends = attrs["starts_at"], attrs["ends_at"]
        if ends <= starts:
            raise serializers.ValidationError({"ends_at": "Must be after the start time."})
        if ends <= timezone.now():
            raise serializers.ValidationError({"ends_at": "Must be in the future."})
        seen = set()
        for item in attrs["items"]:
            variant = item["variant"]
            if variant.id in seen:
                raise serializers.ValidationError({"items": f"{variant.sku} is listed twice."})
            seen.add(variant.id)
            if item["sale_price"] >= variant.price:
                raise serializers.ValidationError(
                    {"items": f"{variant.sku}: the sale price must be below the regular price of {variant.price}."}
                )
            if flash_sales.clashing_items(variant.id, starts, ends).exists():
                raise serializers.ValidationError(
                    {"items": f"{variant.sku} is already in another sale that overlaps this one."}
                )
        return attrs

    def create(self, validated_data):
        items = validated_data.pop("items")
        with transaction.atomic():
            sale = FlashSale.objects.create(**validated_data)
            FlashSaleItem.objects.bulk_create(FlashSaleItem(sale=sale, **item) for item in items)
            # A sale that is already running, or starts soon, changes what search shows for its products.
            product_ids = {item.variant.product_id for item in sale.items.select_related("variant")}
            transaction.on_commit(lambda: [events.announce_product(pid) for pid in product_ids])
        return sale


class FlashSaleStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = FlashSale
        fields = ["id", "name", "starts_at", "ends_at", "is_active"]
        read_only_fields = ["id", "name", "starts_at", "ends_at"]

    def update(self, instance, validated_data):
        with transaction.atomic():
            instance = super().update(instance, validated_data)
            product_ids = {item.variant.product_id for item in instance.items.select_related("variant")}
            transaction.on_commit(lambda: [events.announce_product(pid) for pid in product_ids])
        return instance

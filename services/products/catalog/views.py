from django.conf import settings
from django.core.cache import cache
from django.shortcuts import get_object_or_404
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .filters import ProductFilter
from .models import Category, Product, ProductImage, ProductVariant
from .permissions import (
    IsAdminOrReadOnly,
    IsProductOwnerOrAdmin,
    IsSellerOrAdmin,
    is_admin,
    user_id_of,
)
from .serializers import (
    CategorySerializer,
    ImageSerializer,
    ProductDetailSerializer,
    ProductListSerializer,
    ProductWriteSerializer,
    VariantSerializer,
)
from .signals import CATEGORY_TREE_CACHE_KEY

PRODUCT_SEARCH_FIELDS = ["name", "brand", "description"]
PRODUCT_ORDERING_FIELDS = ["min_price", "created_at", "name"]


class CategoryViewSet(viewsets.ModelViewSet):
    serializer_class = CategorySerializer
    permission_classes = [IsAdminOrReadOnly]
    lookup_field = "slug"
    pagination_class = None

    def get_queryset(self):
        queryset = Category.objects.select_related("parent")
        return queryset if is_admin(self.request) else queryset.filter(is_active=True)

    def perform_destroy(self, instance):
        # Deactivate instead of deleting: products and old orders still point at it.
        instance.is_active = False
        instance.save(update_fields=["is_active"])

    @action(detail=False, permission_classes=[permissions.AllowAny])
    def tree(self, request):
        """All active categories as a nested tree, cached in Redis."""
        tree = cache.get(CATEGORY_TREE_CACHE_KEY)
        if tree is None:
            nodes = {
                c.id: {"name": c.name, "slug": c.slug, "parent_id": c.parent_id, "children": []}
                for c in Category.objects.filter(is_active=True)
            }
            tree = []
            for node in nodes.values():
                parent = nodes.get(node["parent_id"])
                (parent["children"] if parent else tree).append(node)
            for node in nodes.values():
                del node["parent_id"]
            cache.set(CATEGORY_TREE_CACHE_KEY, tree, settings.CATEGORY_CACHE_SECONDS)
        return Response(tree)


class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    """Public storefront catalogue: only published products in active categories."""

    permission_classes = [permissions.AllowAny]
    lookup_field = "slug"
    filterset_class = ProductFilter
    search_fields = PRODUCT_SEARCH_FIELDS
    ordering_fields = PRODUCT_ORDERING_FIELDS
    ordering = ["-created_at"]

    def get_queryset(self):
        return Product.objects.active().with_listing_data()

    def get_serializer_class(self):
        return ProductListSerializer if self.action == "list" else ProductDetailSerializer


class SellerProductViewSet(viewsets.ModelViewSet):
    """Sellers manage their own products here (drafts included); admins see every product."""

    permission_classes = [IsSellerOrAdmin, IsProductOwnerOrAdmin]
    filterset_class = ProductFilter
    search_fields = PRODUCT_SEARCH_FIELDS
    ordering_fields = PRODUCT_ORDERING_FIELDS
    ordering = ["-created_at"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        queryset = Product.objects.with_listing_data()
        if is_admin(self.request):
            return queryset
        # Ownership: a seller's queryset never contains anyone else's products,
        # so someone else's product id returns 404.
        return queryset.filter(seller_id=user_id_of(self.request))

    def get_serializer_class(self):
        if self.action in ("create", "partial_update"):
            return ProductWriteSerializer
        if self.action == "list":
            return ProductListSerializer
        return ProductDetailSerializer

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "show_inactive": True}

    def perform_create(self, serializer):
        serializer.save(seller_id=user_id_of(self.request))

    def perform_destroy(self, instance):
        # Archive instead of deleting, so past orders can still show what was bought.
        instance.status = Product.Status.ARCHIVED
        instance.save(update_fields=["status", "updated_at"])


class ProductChildViewSet(mixins.CreateModelMixin, mixins.UpdateModelMixin,
                          mixins.DestroyModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """Base for /seller/products/{product_id}/variants|images/."""

    permission_classes = [IsSellerOrAdmin, IsProductOwnerOrAdmin]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    model = None

    def get_product(self):
        if not hasattr(self, "_product"):
            products = Product.objects.all()
            if not is_admin(self.request):
                products = products.filter(seller_id=user_id_of(self.request))
            self._product = get_object_or_404(products, pk=self.kwargs["product_pk"])
        return self._product

    def get_queryset(self):
        return self.model.objects.filter(product=self.get_product())

    def perform_create(self, serializer):
        serializer.save(product=self.get_product())


class VariantViewSet(ProductChildViewSet):
    serializer_class = VariantSerializer
    model = ProductVariant

    def perform_destroy(self, instance):
        # Deactivate rather than delete: orders and stock records refer to the SKU.
        instance.is_active = False
        instance.save(update_fields=["is_active"])

    def perform_update(self, serializer):
        variant = serializer.save()
        product = variant.product
        # Don't leave a published product with nothing to buy.
        if product.status == Product.Status.ACTIVE and not product.variants.filter(is_active=True).exists():
            product.status = Product.Status.DRAFT
            product.save(update_fields=["status", "updated_at"])


class ImageViewSet(ProductChildViewSet):
    serializer_class = ImageSerializer
    model = ProductImage

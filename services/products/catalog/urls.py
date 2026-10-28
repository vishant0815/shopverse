from django.urls import include, path
from rest_framework.routers import DefaultRouter, SimpleRouter

from . import views

router = DefaultRouter()
router.register("categories", views.CategoryViewSet, basename="category")
router.register("products", views.ProductViewSet, basename="product")
router.register("seller/products", views.SellerProductViewSet, basename="seller-product")

product_children = SimpleRouter()
product_children.register("variants", views.VariantViewSet, basename="variant")
product_children.register("images", views.ImageViewSet, basename="image")

urlpatterns = router.urls + [
    path("seller/products/<uuid:product_pk>/", include(product_children.urls)),
]

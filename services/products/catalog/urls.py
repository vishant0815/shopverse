from django.urls import include, path
from rest_framework.routers import DefaultRouter, SimpleRouter

from . import review_views, views

router = DefaultRouter()
router.register("categories", views.CategoryViewSet, basename="category")
router.register("products", views.ProductViewSet, basename="product")
router.register("seller/products", views.SellerProductViewSet, basename="seller-product")

product_children = SimpleRouter()
product_children.register("variants", views.VariantViewSet, basename="variant")
product_children.register("images", views.ImageViewSet, basename="image")

urlpatterns = router.urls + [
    path("variants/lookup/", views.VariantLookupView.as_view(), name="variant-lookup"),
    path("admin/flash-sales/", views.AdminFlashSaleListView.as_view(), name="admin-flash-sales"),
    path("admin/flash-sales/<uuid:pk>/", views.AdminFlashSaleDetailView.as_view(), name="admin-flash-sale"),
    path("seller/products/<uuid:product_pk>/", include(product_children.urls)),
    path("products/<slug:slug>/reviews/", review_views.ProductReviewsView.as_view(), name="product-reviews"),
    path("products/<slug:slug>/reviews/mine/", review_views.ProductReviewMineView.as_view(), name="product-review-mine"),
    path("admin/reviews/", review_views.AdminReviewListView.as_view(), name="admin-reviews"),
    path("admin/reviews/<uuid:pk>/", review_views.AdminReviewDetailView.as_view(), name="admin-review"),
]

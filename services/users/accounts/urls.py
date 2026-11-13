from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("addresses", views.AddressViewSet, basename="address")
router.register("admin/sellers", views.AdminSellerViewSet, basename="admin-seller")

urlpatterns = [
    path("auth/register/", views.RegisterView.as_view(), name="register"),
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("auth/refresh/", views.RefreshView.as_view(), name="token-refresh"),
    path("auth/logout/", views.LogoutView.as_view(), name="logout"),
    path("users/me/", views.MeView.as_view(), name="me"),
    path("users/me/change-password/", views.ChangePasswordView.as_view(), name="change-password"),
    path("sellers/me/", views.SellerProfileView.as_view(), name="seller-me"),
] + router.urls

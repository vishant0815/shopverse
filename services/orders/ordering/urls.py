from django.urls import path

from . import views

urlpatterns = [
    path("cart/", views.CartView.as_view(), name="cart"),
    path("cart/items/", views.CartItemsView.as_view(), name="cart-items"),
    path("cart/items/<uuid:variant_id>/", views.CartItemDetailView.as_view(), name="cart-item"),
    path("checkout/", views.CheckoutView.as_view(), name="checkout"),
    path("orders/", views.MyOrdersView.as_view(), name="my-orders"),
    path("orders/<str:number>/", views.MyOrderDetailView.as_view(), name="my-order"),
    path("orders/<str:number>/cancel/", views.CancelOrderView.as_view(), name="cancel-order"),
    path("seller/sales/", views.SellerSalesView.as_view(), name="seller-sales"),
    path("admin/orders/", views.AdminOrderListView.as_view(), name="admin-orders"),
    path("admin/orders/<str:number>/", views.AdminOrderDetailView.as_view(), name="admin-order"),
    path("admin/orders/<str:number>/transition/", views.AdminTransitionView.as_view(), name="admin-transition"),
]

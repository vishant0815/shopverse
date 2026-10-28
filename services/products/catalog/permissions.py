"""Authorisation based on the claims inside the JWT issued by the users service."""

from rest_framework.permissions import SAFE_METHODS, BasePermission


def role_of(request):
    token = getattr(request, "auth", None)
    return token.get("role") if token is not None else None


def user_id_of(request):
    token = getattr(request, "auth", None)
    return str(token.get("user_id")) if token is not None else None


def is_admin(request):
    return role_of(request) == "admin"


class IsAdminOrReadOnly(BasePermission):
    message = "Only admins can change categories."

    def has_permission(self, request, view):
        return request.method in SAFE_METHODS or is_admin(request)


class IsSellerOrAdmin(BasePermission):
    message = "Only sellers and admins can manage products."

    def has_permission(self, request, view):
        return role_of(request) in ("seller", "admin")


class IsProductOwnerOrAdmin(BasePermission):
    """Sellers can only touch their own products; admins can touch any."""

    message = "You can only manage your own products."

    def has_object_permission(self, request, view, obj):
        product = getattr(obj, "product", obj)
        return is_admin(request) or str(product.seller_id) == user_id_of(request)

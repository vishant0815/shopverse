"""Authorisation based on the claims inside the JWT issued by the users service."""

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import SellerStatus


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


NOT_APPROVED_MESSAGES = {
    "suspended": "Your shop is suspended, so you can't change products.",
}
PENDING_MESSAGE = "Your shop is waiting for approval, so you can't change products yet."


def seller_status(seller_id):
    """The approval status the users service last announced for this seller, or None."""
    if not seller_id:
        return None
    return SellerStatus.objects.filter(seller_id=seller_id).values_list("status", flat=True).first()


class IsSellerOrAdmin(BasePermission):
    """Sellers and admins reach the seller endpoints. Sellers can read their own products
    at any time, but only an approved shop can change them."""

    message = "Only sellers and admins can manage products."

    def has_permission(self, request, view):
        role = role_of(request)
        if role == "admin":
            return True
        if role != "seller":
            return False
        if request.method in SAFE_METHODS:
            return True
        status = seller_status(user_id_of(request))
        if status == SellerStatus.Status.APPROVED:
            return True
        raise PermissionDenied(detail=NOT_APPROVED_MESSAGES.get(status, PENDING_MESSAGE))


class IsProductOwnerOrAdmin(BasePermission):
    """Sellers can only touch their own products; admins can touch any."""

    message = "You can only manage your own products."

    def has_object_permission(self, request, view, obj):
        product = getattr(obj, "product", obj)
        return is_admin(request) or str(product.seller_id) == user_id_of(request)

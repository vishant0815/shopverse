"""Authorisation based on the claims inside the JWT issued by the users service."""

from rest_framework.permissions import BasePermission


def role_of(request):
    token = getattr(request, "auth", None)
    return token.get("role") if token is not None else None


def user_id_of(request):
    token = getattr(request, "auth", None)
    return str(token.get("user_id")) if token is not None else None


class IsCustomer(BasePermission):
    """Any signed-in user can shop, sellers and admins included."""

    def has_permission(self, request, view):
        return user_id_of(request) is not None


class IsSeller(BasePermission):
    message = "Only sellers can view sales."

    def has_permission(self, request, view):
        return role_of(request) == "seller"


class IsAdmin(BasePermission):
    message = "Only admins can do this."

    def has_permission(self, request, view):
        return role_of(request) == "admin"


class IsService(BasePermission):
    """Other Shopverse services (e.g. payments) calling with a short-lived service token."""

    message = "Only internal services can do this."

    def has_permission(self, request, view):
        return role_of(request) == "service"

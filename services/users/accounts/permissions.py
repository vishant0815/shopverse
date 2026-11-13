from rest_framework.permissions import BasePermission


class IsSeller(BasePermission):
    message = "Only sellers can manage a shop."

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == "seller"


class IsAdmin(BasePermission):
    message = "Only admins can do that."

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == "admin"

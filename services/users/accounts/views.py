from django.conf import settings
from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .models import SellerProfile, User
from .permissions import IsAdmin, IsSeller
from .sellers import InvalidTransition, change_status
from .serializers import (
    AddressSerializer,
    AdminSellerSerializer,
    ChangePasswordSerializer,
    LoginSerializer,
    RegisterSerializer,
    SellerProfileSerializer,
    UserSerializer,
)


def set_refresh_cookie(response, refresh_token):
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=str(refresh_token),
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
        path=settings.REFRESH_COOKIE_PATH,
    )


def clear_refresh_cookie(response):
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        path=settings.REFRESH_COOKIE_PATH,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
    )


def token_response(user, status_code=status.HTTP_200_OK):
    """Access token goes in the body; refresh token goes in an httpOnly cookie."""
    refresh = RefreshToken.for_user(user)
    refresh["role"] = user.role
    access = refresh.access_token
    access["role"] = user.role
    response = Response(
        {"access": str(access), "user": UserSerializer(user).data},
        status=status_code,
    )
    set_refresh_cookie(response, refresh)
    return response


class AuthThrottleMixin:
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


class RegisterView(AuthThrottleMixin, generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return token_response(user, status.HTTP_201_CREATED)


class LoginView(AuthThrottleMixin, APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        return token_response(serializer.validated_data["user"])


class RefreshView(AuthThrottleMixin, APIView):
    """Issues a new access token and rotates the refresh token.
    The old refresh token is blacklisted, so a stolen one can only be used once."""

    # Its own, roomier limit: sharing sign-in's would log people out for browsing quickly.
    throttle_scope = "refresh"
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        raw = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if not raw:
            return Response({"detail": "Refresh token missing."}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            old = RefreshToken(raw)
            user_id = old["user_id"]
            role = old.get("role")
            old.blacklist()
        except TokenError:
            response = Response({"detail": "Refresh token invalid or expired."}, status=status.HTTP_401_UNAUTHORIZED)
            clear_refresh_cookie(response)
            return response

        user = User.objects.filter(id=user_id, is_active=True).first()
        if user is None:
            response = Response({"detail": "User not found or inactive."}, status=status.HTTP_401_UNAUTHORIZED)
            clear_refresh_cookie(response)
            return response

        new_refresh = RefreshToken.for_user(user)
        new_refresh["role"] = user.role
        access = new_refresh.access_token
        access["role"] = user.role
        response = Response({"access": str(access)})
        set_refresh_cookie(response, new_refresh)
        return response


class LogoutView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        raw = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if raw:
            try:
                RefreshToken(raw).blacklist()
            except TokenError:
                pass
        response = Response(status=status.HTTP_204_NO_CONTENT)
        clear_refresh_cookie(response)
        return response


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        return self.request.user


class ChangePasswordView(APIView):
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password", "updated_at"])
        # Log the user out of the current refresh session as well.
        response = Response({"detail": "Password changed. Please log in again."})
        raw = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if raw:
            try:
                RefreshToken(raw).blacklist()
            except TokenError:
                pass
        clear_refresh_cookie(response)
        return response


class AddressViewSet(viewsets.ModelViewSet):
    serializer_class = AddressSerializer

    def get_queryset(self):
        # Ownership check: users only ever see their own addresses.
        # Another user's address id returns 404, not 403, so ids can't be probed.
        return self.request.user.addresses.all()

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class SellerProfileView(generics.RetrieveUpdateAPIView):
    """A seller's own shop: its name and description. Approval is an admin's decision."""

    serializer_class = SellerProfileSerializer
    permission_classes = [IsSeller]
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        try:
            return self.request.user.seller_profile
        except SellerProfile.DoesNotExist:
            raise NotFound("This account has no shop.")


class AdminSellerViewSet(viewsets.ReadOnlyModelViewSet):
    """Every seller's shop, for admins. Approve or suspend a seller from here.

    The id in the URL is the seller's user id, the same id products and orders use."""

    serializer_class = AdminSellerSerializer
    permission_classes = [IsAdmin]
    lookup_field = "user_id"
    lookup_value_regex = r"[0-9a-fA-F-]{36}"

    def get_queryset(self):
        queryset = SellerProfile.objects.select_related("user")
        wanted = self.request.query_params.get("status")
        if wanted:
            queryset = queryset.filter(status=wanted)
        return queryset

    def _move_to(self, new_status):
        profile = self.get_object()
        try:
            profile = change_status(profile, new_status)
        except InvalidTransition as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(self.get_serializer(profile).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, user_id=None):
        return self._move_to(SellerProfile.Status.APPROVED)

    @action(detail=True, methods=["post"])
    def suspend(self, request, user_id=None):
        return self._move_to(SellerProfile.Status.SUSPENDED)


from django.contrib.auth import authenticate, password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Address, User


def check_password_strength(password, user, field):
    """Run Django's password rules and report problems against the password field,
    so a form can show them next to the right input."""
    try:
        password_validation.validate_password(password, user=user)
    except DjangoValidationError as error:
        raise serializers.ValidationError({field: list(error.messages)})


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "full_name", "phone", "role", "date_joined"]
        # Email and role can't be changed through the profile endpoint.
        read_only_fields = ["id", "email", "role", "date_joined"]


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    # Admins are never created through public signup.
    role = serializers.ChoiceField(
        choices=[User.Role.CUSTOMER, User.Role.SELLER], default=User.Role.CUSTOMER
    )

    class Meta:
        model = User
        fields = ["email", "password", "first_name", "last_name", "phone", "role"]

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate(self, attrs):
        candidate = User(
            email=attrs.get("email"),
            first_name=attrs.get("first_name", ""),
            last_name=attrs.get("last_name", ""),
        )
        check_password_strength(attrs["password"], candidate, field="password")
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        return User.objects.create_user(password=password, **validated_data)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get("request"),
            email=attrs["email"].strip().lower(),
            password=attrs["password"],
        )
        # Same message for a wrong email or a wrong password,
        # so the endpoint can't be used to find out which emails are registered.
        if user is None or not user.is_active:
            raise serializers.ValidationError("Invalid email or password.", code="authorization")
        attrs["user"] = user
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_current_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate(self, attrs):
        check_password_strength(attrs["new_password"], self.context["request"].user, field="new_password")
        return attrs


class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = [
            "id",
            "full_name",
            "phone",
            "line1",
            "line2",
            "city",
            "county",
            "postcode",
            "country",
            "is_default",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_postcode(self, value):
        return value.strip().upper()

    def validate_country(self, value):
        value = value.strip().upper()
        if len(value) != 2 or not value.isalpha():
            raise serializers.ValidationError("Use a two-letter country code, e.g. GB.")
        return value

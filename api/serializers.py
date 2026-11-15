import math
import re
from collections.abc import Mapping

from django.core.validators import URLValidator
from rest_framework import serializers

from .models import *

USERNAME_PATTERN = re.compile(r"^[a-z0-9_.]+$")
COMMON_PASSWORDS = {"password", "password1", "12345678", "qwertyui", "iloveyou", "admin123"}


# --------------------------------------------------------------- custom fields
class StrictCharField(serializers.CharField):
    """CharField that refuses numbers, booleans, lists and dicts."""

    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


def text_field(max_length: int, *, required: bool = True, allow_blank: bool = False, **kwargs):
    return StrictCharField(
        max_length=max_length, required=required, allow_blank=allow_blank, **kwargs
    )


class UsernameField(StrictCharField):
    default_error_messages = {
        "pattern": "Use only letters, numbers, dots and underscores.",
    }

    def __init__(self, **kwargs):
        kwargs.setdefault("min_length", USERNAME_MIN_LENGTH)
        kwargs.setdefault("max_length", USERNAME_MAX_LENGTH)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        value = super().to_internal_value(data).lower()
        if not USERNAME_PATTERN.match(value):
            self.fail("pattern")
        return value


class EmailAddressField(serializers.EmailField):
    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", EMAIL_MAX_LENGTH)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data).lower()


class PasswordField(StrictCharField):
    def __init__(self, **kwargs):
        kwargs.setdefault("write_only", True)
        kwargs.setdefault("trim_whitespace", False)
        kwargs.setdefault("max_length", PASSWORD_MAX_LENGTH)
        kwargs.setdefault("style", {"input_type": "password"})
        super().__init__(**kwargs)


class WebURLField(StrictCharField):
    """http/https URL, used for image links and the website field."""

    default_error_messages = {"url": "Enter a valid http or https URL."}

    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", URL_MAX_LENGTH)
        kwargs.setdefault("allow_blank", True)
        kwargs.setdefault("required", False)
        super().__init__(**kwargs)
        self.validators.append(URLValidator(schemes=["http", "https"], message=self.error_messages["url"]))


class QueryBooleanField(serializers.ChoiceField):
    """?is_pinned=true / false. A missing parameter stays missing (not False)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        super().__init__(choices=("true", "false"), **kwargs)

    def to_internal_value(self, data):
        return super().to_internal_value(str(data).lower()) == "true"


class ObjectIdField(serializers.Field):
    def to_representation(self, value):
        return str(value)

    def to_internal_value(self, data):
        return to_object_id(data, self.field_name or "id")


def ensure_strong_password(password: str, *, username: str = "", email: str = "", field: str = "password") -> None:
    errors = []
    if len(password) < PASSWORD_MIN_LENGTH:
        errors.append(f"Password must be at least {PASSWORD_MIN_LENGTH} characters long.")
    if not re.search(r"[a-z]", password):
        errors.append("Password must contain a lowercase letter.")
    if not re.search(r"[A-Z]", password):
        errors.append("Password must contain an uppercase letter.")
    if not re.search(r"\d", password):
        errors.append("Password must contain a number.")
    if not re.search(r"[^A-Za-z0-9]", password):
        errors.append("Password must contain a special character.")
    if password.lower() in COMMON_PASSWORDS:
        errors.append("Password is too common.")

    lowered = password.lower()
    email_name = email.split("@")[0] if email else ""
    for personal in (username, email_name):
        if len(personal) >= 3 and personal.lower() in lowered:
            errors.append("Password must not contain your username or email.")
            break

    if errors:
        raise serializers.ValidationError({field: errors})


class StrictSerializer(serializers.Serializer):
    """Rejects any key that is not declared on the serializer."""

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            unknown = set(data.keys()) - set(self.fields.keys())
            if unknown:
                raise serializers.ValidationError(
                    {name: ["This field is not allowed."] for name in sorted(unknown)}
                )
        return super().to_internal_value(data)


class AtLeastOneFieldMixin:
    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Provide at least one field to update.")
        return super().validate(attrs)


# ------------------------------------------------------------------- pagination
def pagination_meta(page: int, page_size: int, total: int) -> dict:
    total_pages = math.ceil(total / page_size) if total else 0
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_previous": page > 1,
    }


class PaginationSerializer(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, max_value=MAX_PAGE, default=1)
    page_size = serializers.IntegerField(
        min_value=1, max_value=MAX_PAGE_SIZE, default=DEFAULT_PAGE_SIZE
    )


# --------------------------------------------------------------- authentication
class RegisterSerializer(StrictSerializer):
    """Public registration. There is no role field, so a role can never be sent."""

    username = UsernameField()
    full_name = text_field(FULL_NAME_MAX_LENGTH)
    email = EmailAddressField()
    password = PasswordField()
    interests = serializers.ListField(
        child=StrictCharField(max_length=INTEREST_MAX_LENGTH),
        max_length=MAX_INTERESTS,
        required=False,
    )

    def validate_interests(self, value):
        return normalize_string_list(value)

    def validate(self, attrs):
        ensure_strong_password(
            attrs["password"], username=attrs["username"], email=attrs["email"]
        )
        return attrs


class LoginSerializer(StrictSerializer):
    email = EmailAddressField()
    password = PasswordField()


class RefreshTokenSerializer(StrictSerializer):
    refresh = StrictCharField(max_length=2048)


class ForgotPasswordSerializer(StrictSerializer):
    email = EmailAddressField()


class ResetPasswordSerializer(StrictSerializer):
    token = StrictCharField(max_length=256)
    new_password = PasswordField()

    def validate(self, attrs):
        ensure_strong_password(attrs["new_password"], field="new_password")
        return attrs


# ------------------------------------------------------------------------ users
class ProfileFieldsSerializer(StrictSerializer):
    full_name = text_field(FULL_NAME_MAX_LENGTH, required=False)
    bio = text_field(BIO_MAX_LENGTH, required=False, allow_blank=True)
    interests = serializers.ListField(
        child=StrictCharField(max_length=INTEREST_MAX_LENGTH),
        max_length=MAX_INTERESTS,
        required=False,
    )
    profile_image = WebURLField()
    cover_image = WebURLField()
    location = text_field(LOCATION_MAX_LENGTH, required=False, allow_blank=True)
    website = WebURLField()

    def validate_interests(self, value):
        return normalize_string_list(value)


class UserUpdateSerializer(AtLeastOneFieldMixin, ProfileFieldsSerializer):
    """Self profile update (use with partial=True). No role, email or status."""

    username = UsernameField(required=False)


class AdminUserCreateSerializer(ProfileFieldsSerializer):
    username = UsernameField()
    email = EmailAddressField()
    password = PasswordField()
    role = serializers.ChoiceField(choices=ROLES, required=False)
    is_active = serializers.BooleanField(required=False)
    is_verified = serializers.BooleanField(required=False)

    def validate(self, attrs):
        ensure_strong_password(
            attrs["password"], username=attrs["username"], email=attrs["email"]
        )
        return attrs


class AdminUserUpdateSerializer(AtLeastOneFieldMixin, ProfileFieldsSerializer):
    """PUT needs username, email and role. PATCH uses partial=True."""

    username = UsernameField()
    email = EmailAddressField()
    role = serializers.ChoiceField(choices=ROLES)
    password = PasswordField(required=False)
    is_active = serializers.BooleanField(required=False)
    is_verified = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if "password" in attrs:
            ensure_strong_password(
                attrs["password"],
                username=attrs.get("username", ""),
                email=attrs.get("email", ""),
            )
        return super().validate(attrs)


# ------------------------------------------------------------------------ notes
class NoteCreateSerializer(StrictSerializer):
    title = text_field(NOTE_TITLE_MAX_LENGTH)
    content = text_field(NOTE_CONTENT_MAX_LENGTH, trim_whitespace=False)
    color = serializers.ChoiceField(choices=NOTE_COLORS, required=False)
    tags = serializers.ListField(
        child=StrictCharField(max_length=TAG_MAX_LENGTH), max_length=MAX_TAGS, required=False
    )
    is_pinned = serializers.BooleanField(required=False)
    is_archived = serializers.BooleanField(required=False)

    def validate_tags(self, value):
        return normalize_string_list(value)


class NoteUpdateSerializer(AtLeastOneFieldMixin, NoteCreateSerializer):
    """PUT needs title and content. PATCH uses partial=True."""


# ------------------------------------------------------------------------ posts
class PostCreateSerializer(StrictSerializer):
    title = text_field(POST_TITLE_MAX_LENGTH)
    content = text_field(POST_CONTENT_MAX_LENGTH, trim_whitespace=False)
    summary = text_field(POST_SUMMARY_MAX_LENGTH, required=False, allow_blank=True)
    cover_image = WebURLField()
    tags = serializers.ListField(
        child=StrictCharField(max_length=TAG_MAX_LENGTH), max_length=MAX_TAGS, required=False
    )
    is_published = serializers.BooleanField(required=False)

    def validate_tags(self, value):
        return normalize_string_list(value)


class PostUpdateSerializer(AtLeastOneFieldMixin, PostCreateSerializer):
    """PUT needs title and content. PATCH uses partial=True."""


# ------------------------------------------------------------------ query params
class NoteQuerySerializer(PaginationSerializer):
    """`user_id` is honoured for admins only (the view ignores it otherwise)."""

    search = StrictCharField(max_length=SEARCH_MAX_LENGTH, required=False)
    is_pinned = QueryBooleanField()
    is_archived = QueryBooleanField()
    user_id = ObjectIdField(required=False)
    ordering = serializers.ChoiceField(
        choices=("created_at", "-created_at", "updated_at", "-updated_at"),
        default="-created_at",
    )


class UserQuerySerializer(PaginationSerializer):
    search = StrictCharField(max_length=SEARCH_MAX_LENGTH, required=False)
    role = serializers.ChoiceField(choices=ROLES, required=False)
    is_active = QueryBooleanField()
    ordering = serializers.ChoiceField(
        choices=("created_at", "-created_at"), default="-created_at"
    )


class PostQuerySerializer(PaginationSerializer):
    search = StrictCharField(max_length=SEARCH_MAX_LENGTH, required=False)
    tag = StrictCharField(max_length=TAG_MAX_LENGTH, required=False)
    is_published = QueryBooleanField()
    ordering = serializers.ChoiceField(
        choices=("created_at", "-created_at"), default="-created_at"
    )


# ---------------------------------------------------------------------- responses
class ReadSerializer(serializers.Serializer):
    """Output only. Keys missing from a document are skipped, not errors."""

    def get_fields(self):
        fields = super().get_fields()
        for field in fields.values():
            field.required = False
        return fields


class UserSerializer(ReadSerializer):
    id = ObjectIdField(source="_id")
    username = serializers.CharField()
    full_name = serializers.CharField()
    email = serializers.CharField()
    role = serializers.CharField()
    interests = serializers.ListField(child=serializers.CharField())
    bio = serializers.CharField()
    profile_image = serializers.CharField()
    cover_image = serializers.CharField()
    location = serializers.CharField()
    website = serializers.CharField()
    is_active = serializers.BooleanField()
    is_verified = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class PublicUserSerializer(ReadSerializer):
    """What strangers may see: no email, role or account status."""

    id = ObjectIdField(source="_id")
    username = serializers.CharField()
    full_name = serializers.CharField()
    bio = serializers.CharField()
    interests = serializers.ListField(child=serializers.CharField())
    profile_image = serializers.CharField()
    cover_image = serializers.CharField()
    location = serializers.CharField()
    website = serializers.CharField()
    created_at = serializers.DateTimeField()


class NoteSerializer(ReadSerializer):
    id = ObjectIdField(source="_id")
    user_id = ObjectIdField()
    title = serializers.CharField()
    content = serializers.CharField()
    color = serializers.CharField()
    tags = serializers.ListField(child=serializers.CharField())
    is_pinned = serializers.BooleanField()
    is_archived = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class PostListSerializer(ReadSerializer):
    """Lists skip the heavy `content` field."""

    id = ObjectIdField(source="_id")
    user_id = ObjectIdField()
    title = serializers.CharField()
    summary = serializers.CharField()
    cover_image = serializers.CharField()
    tags = serializers.ListField(child=serializers.CharField())
    is_published = serializers.BooleanField()
    published_at = serializers.DateTimeField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class PostSerializer(PostListSerializer):
    content = serializers.CharField()


class UserWithPostsSerializer(PublicUserSerializer):
    posts = PostListSerializer(many=True)


class InterestUserSerializer(ReadSerializer):
    id = ObjectIdField(source="_id")
    username = serializers.CharField()
    full_name = serializers.CharField()
    profile_image = serializers.CharField()


class InterestGroupSerializer(ReadSerializer):
    interest = serializers.CharField()
    user_count = serializers.IntegerField()
    users = InterestUserSerializer(many=True)
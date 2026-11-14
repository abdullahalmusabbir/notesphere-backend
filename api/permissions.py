"""All permission rules live here. Views only pick the right class."""
from bson import ObjectId
from django.conf import settings
from rest_framework.permissions import SAFE_METHODS, BasePermission

from .exceptions import PayloadTooLarge
from .models import ROLE_ADMIN

DEFAULT_MAX_BODY_BYTES = 1_048_576  # 1 MB


# -------------------------------------------------------------------- helpers
def is_authenticated(user) -> bool:
    return bool(user and getattr(user, "is_authenticated", False))


def is_admin(user) -> bool:
    return is_authenticated(user) and getattr(user, "role", None) == ROLE_ADMIN


def ownership_filter(user) -> dict:
    """Base MongoDB filter for notes/posts. Admins see everything, everybody
    else is limited to documents whose user_id is their own JWT identity."""
    if is_admin(user):
        return {}
    return {"user_id": user.id}


def can_view_unpublished_posts(user, owner_id: ObjectId) -> bool:
    return is_admin(user) or (is_authenticated(user) and user.id == owner_id)


def _enforce_body_size_limit(request) -> None:
    limit = getattr(settings, "MAX_REQUEST_BODY_BYTES", DEFAULT_MAX_BODY_BYTES)
    try:
        length = int(request.META.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        length = limit + 1
    if length > limit:
        raise PayloadTooLarge()


# -------------------------------------------------------------------- classes
class SecureBasePermission(BasePermission):
    """DRF does not limit body size on its own, so every permission class
    checks Content-Length before the body is parsed."""

    def has_permission(self, request, view) -> bool:
        _enforce_body_size_limit(request)
        return self.is_allowed(request, view)

    def is_allowed(self, request, view) -> bool:
        return True


class PublicEndpoint(SecureBasePermission):
    """Anyone can call it (register, login, public posts)."""


class IsAuthenticatedUser(SecureBasePermission):
    message = "Authentication credentials were not provided."

    def is_allowed(self, request, view) -> bool:
        return is_authenticated(request.user)


class IsAdmin(SecureBasePermission):
    message = "Admin access is required."

    def is_allowed(self, request, view) -> bool:
        return is_admin(request.user)


class ReadOnlyOrAuthenticated(SecureBasePermission):
    """Safe methods are public, anything that writes needs a login."""

    def is_allowed(self, request, view) -> bool:
        return request.method in SAFE_METHODS or is_authenticated(request.user)


class IsOwnerOrAdmin(SecureBasePermission):
    """Object level rule for notes and posts (documents with a user_id)."""

    message = "You do not have permission to access this resource."

    def is_allowed(self, request, view) -> bool:
        return is_authenticated(request.user)

    def has_object_permission(self, request, view, obj) -> bool:
        return is_admin(request.user) or obj.get("user_id") == request.user.id


class IsSelfOrAdmin(SecureBasePermission):
    """Object level rule for user documents."""

    message = "You do not have permission to access this account."

    def is_allowed(self, request, view) -> bool:
        return is_authenticated(request.user)

    def has_object_permission(self, request, view, obj) -> bool:
        return is_admin(request.user) or obj.get("_id") == request.user.id


class IsPublishedOrOwnerOrAdmin(IsOwnerOrAdmin):
    """Posts: published ones can be read by anyone, writes and drafts are
    for the owner or an admin."""

    def is_allowed(self, request, view) -> bool:
        return request.method in SAFE_METHODS or is_authenticated(request.user)

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in SAFE_METHODS and obj.get("is_published") is True:
            return True
        return is_authenticated(request.user) and super().has_object_permission(
            request, view, obj
        )

class CanCreatePost(SecureBasePermission):
    """Create a post: open to every authenticated user (role "user" or "admin");
    read is public."""

    message = "You do not have permission to create a post."

    def is_allowed(self, request, view) -> bool:
        return request.method in SAFE_METHODS or is_authenticated(request.user)
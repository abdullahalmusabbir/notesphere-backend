from rest_framework.exceptions import NotFound, ValidationError

from db_connection import get_collection

from .authentications import hash_password
from .exceptions import conflict_from_duplicate_key
from .models import (
    ROLE_ADMIN,
    ROLE_USER,
    USERS_COLLECTION,
    new_user_document,
    normalize_string_list,
    to_object_id,
    utc_now,
)
from .permissions import is_admin

_USERS = get_collection(USERS_COLLECTION)


def _pick(data: dict, allowed: tuple) -> dict:
    changes = {key: data[key] for key in allowed if key in data}
    if not changes:
        raise ValidationError({"non_field_errors": ["No valid fields to update."]})
    return changes


def _strip_password(document: dict | None) -> dict | None:
    if document is None:
        return None
    document.pop("password", None)
    return document


def get_user(user_id: str) -> dict:
    """Return a user document without the password hash, or 404."""
    user = _USERS.find_one({"_id": to_object_id(user_id, "user_id")})
    if user is None:
        raise NotFound("User not found.")
    return _strip_password(user)


def list_users(page: int, page_size: int, *, search: str | None = None,
               role: str | None = None, is_active: bool | None = None,
               ordering: str = "-created_at") -> tuple[list[dict], int]:
    """Paginated user list with optional filters. Password hashes are stripped."""
    query: dict = {}
    if search:
        query["$or"] = [
            {"username": {"$regex": __import__("re").escape(search.strip()), "$options": "i"}},
            {"email": {"$regex": __import__("re").escape(search.strip()), "$options": "i"}},
            {"full_name": {"$regex": __import__("re").escape(search.strip()), "$options": "i"}},
        ]
    if role in (ROLE_USER, ROLE_ADMIN):
        query["role"] = role
    if is_active is not None:
        query["is_active"] = is_active

    from .docker_services import _paginate, _sort_spec

    cursor = (
        _USERS.find(query)
        .sort(_sort_spec(ordering))
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    users = [_strip_password(u) for u in cursor]
    total = _USERS.count_documents(query)
    return users, total


def create_user(data: dict) -> dict:
    """Create a new user. Role defaults to user; password is required."""
    if "password" not in data:
        raise ValidationError({"password": ["This field is required."]})

    document = new_user_document(
        username=data["username"],
        email=data["email"],
        password_hash=hash_password(data["password"]),
        full_name=data.get("full_name", ""),
        role=data.get("role", ROLE_USER),
        interests=data.get("interests", []),
        bio=data.get("bio", ""),
        profile_image=data.get("profile_image", ""),
        cover_image=data.get("cover_image", ""),
        location=data.get("location", ""),
        website=data.get("website", ""),
        is_active=data.get("is_active", True),
        is_verified=data.get("is_verified", False),
    )
    try:
        _USERS.insert_one(document)
    except Exception as exc:  # pragma: no cover - DuplicateKeyError handled by handler
        raise conflict_from_duplicate_key(exc) from exc

    return _strip_password(document)


def update_user(user_id: str, data: dict, *, allowed_fields: tuple,
                acting_user_id: str | None = None) -> dict:
    """Update fields in `allowed_fields` only. Hashes password if present."""
    uid = to_object_id(user_id, "user_id")
    changes = _pick(data, allowed_fields)

    if "password" in changes:
        changes["password"] = hash_password(changes["password"])
    if "interests" in changes:
        changes["interests"] = normalize_string_list(changes["interests"])
    changes["updated_at"] = utc_now()

    user = _USERS.find_one_and_update(
        {"_id": uid},
        {"$set": changes},
        return_document=True,  # ReturnDocument.AFTER
    )
    if user is None:
        raise NotFound("User not found.")
    return _strip_password(user)


def delete_user(user_id: str, acting_user_id: str | None = None) -> None:
    """Soft guard: admins can delete any user; prevent self-delete."""
    uid = to_object_id(user_id, "user_id")
    if acting_user_id and str(uid) == str(acting_user_id):
        raise ValidationError({"non_field_errors": ["You cannot delete your own account."]})

    result = _USERS.delete_one({"_id": uid})
    if result.deleted_count == 0:
        raise NotFound("User not found.")
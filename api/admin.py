"""Admin side user management. Also used for the shared profile update logic."""
from typing import Optional, Union

import re
from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from db_connection import get_collection

from .authentications import *
from .exceptions import *
from .models import *

SAFE_USER_PROJECTION = {"password": 0}
QUERY_TIMEOUT_MS = 5000


def _users():
    return get_collection(USERS_COLLECTION)


def build_user_filter(
    search: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> dict:
    """Build the filter only from checked values, never from raw client input."""
    query: dict = {}

    if isinstance(search, str) and search.strip():
        # username and email are stored in lowercase, so a case sensitive prefix
        # match can use the unique indexes. re.escape stops regex injection.
        prefix = {"$regex": "^" + re.escape(search.strip().lower())}
        query["$or"] = [{"username": prefix}, {"email": prefix}]

    if isinstance(role, str) and role in ROLES:
        query["role"] = role

    if isinstance(is_active, bool):
        query["is_active"] = is_active

    return query


def _sort_spec(ordering: str) -> list:
    direction = DESCENDING if ordering.startswith("-") else ASCENDING
    # _id as a tie breaker keeps pages stable and matches the (created_at, _id) index.
    return [("created_at", direction), ("_id", direction)]


def list_users(
    *,
    page: int,
    page_size: int,
    search: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    ordering: str = "-created_at",
) -> tuple[list[dict], int]:
    query = build_user_filter(search, role, is_active)
    users = _users()

    total = users.count_documents(query, maxTimeMS=QUERY_TIMEOUT_MS)
    cursor = (
        users.find(query, SAFE_USER_PROJECTION)
        .sort(_sort_spec(ordering))
        .skip((page - 1) * page_size)
        .limit(page_size)
        .max_time_ms(QUERY_TIMEOUT_MS)
    )
    return list(cursor), total


def get_user(user_id: Union[str, ObjectId]) -> dict:
    user = _users().find_one({"_id": to_object_id(user_id)}, SAFE_USER_PROJECTION)
    if user is None:
        raise NotFound("User not found.")
    return user


def create_user(data: dict) -> dict:
    """Create a user from already validated serializer data.

    Uniqueness is enforced by the unique indexes, not by a "check then insert"
    query, so two parallel requests cannot create the same email twice.
    """
    extras = {key: data[key] for key in USER_ADMIN_CREATE_FIELDS if key in data}
    document = new_user_document(
        username=data["username"],
        email=data["email"],
        password_hash=hash_password(data["password"]),
        **extras,
    )
    try:
        _users().insert_one(document)
    except DuplicateKeyError as exc:
        raise conflict_from_duplicate_key(exc) from exc

    document.pop("password")
    return document


def update_user(
    user_id: Union[str, ObjectId],
    data: dict,
    *,
    allowed_fields: tuple = USER_ADMIN_EDITABLE_FIELDS,  # ডিফল্ট থাকতে হবে
    acting_user_id: Optional[ObjectId] = None,
) -> dict:
    """Update only allowlisted fields of one user in a single atomic operation.

    Admin endpoints use the default allowlist. The self profile endpoint passes
    USER_SELF_EDITABLE_FIELDS, so role, email and status can never be changed
    from there, even if the client sends them.
    """
    oid = to_object_id(user_id)
    changes = {key: data[key] for key in allowed_fields if key in data}
    if not changes:
        raise ValidationError({"non_field_errors": ["No valid fields to update."]})

    if acting_user_id is not None and acting_user_id == oid:
        demoting = changes.get("role", ROLE_ADMIN) != ROLE_ADMIN
        deactivating = changes.get("is_active", True) is False
        if demoting or deactivating:
            raise PermissionDenied("You cannot demote or deactivate your own account.")

    if "password" in changes:
        changes["password"] = hash_password(changes["password"])
    changes["updated_at"] = utc_now()

    try:
        updated = _users().find_one_and_update(
            {"_id": oid},
            {"$set": changes},
            projection=SAFE_USER_PROJECTION,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError as exc:
        raise conflict_from_duplicate_key(exc) from exc

    if updated is None:
        raise NotFound("User not found.")

    if "password" in changes or "role" in changes or changes.get("is_active") is False:
        revoke_all_user_tokens(oid)
    return updated


def delete_user(user_id: Union[str, ObjectId], acting_user_id: ObjectId) -> None:
    oid = to_object_id(user_id)
    if oid == acting_user_id:
        raise PermissionDenied("You cannot delete your own account.")

    # delete_one is atomic, so when the delete button is clicked twice only one
    # request deletes the user and the other gets a clean 404.
    result = _users().delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise NotFound("User not found.")

    # Cleanup is idempotent and safe to repeat. A multi-document transaction
    # would need a replica set, so the user is removed first and the rest after.
    get_collection(NOTES_COLLECTION).delete_many({"user_id": oid})
    get_collection(POSTS_COLLECTION).delete_many({"user_id": oid})
    revoke_all_user_tokens(oid)
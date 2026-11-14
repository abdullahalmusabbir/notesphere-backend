import hashlib
import logging
import math
import re
import secrets
from datetime import timedelta
from typing import Union

from bson import ObjectId
from django.conf import settings
from django.core.mail import send_mail
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from db_connection import get_collection

from .authentications import (
    dummy_password_check,
    hash_password,
    revoke_all_user_tokens,
    verify_password,
)
from .exceptions import InvalidCredentials, TooManyAttempts, conflict_from_duplicate_key
from .models import (
    LOGIN_ATTEMPTS_COLLECTION,
    NOTE_EDITABLE_FIELDS,
    NOTES_COLLECTION,
    PASSWORD_RESETS_COLLECTION,
    POST_EDITABLE_FIELDS,
    POSTS_COLLECTION,
    USERS_COLLECTION,
    new_note_document,
    new_post_document,
    new_user_document,
    normalize_string_list,
    to_object_id,
    utc_now,
)
from .permissions import can_view_unpublished_posts, is_admin, ownership_filter

logger = logging.getLogger("api")

QUERY_TIMEOUT_MS = 5000
DocumentId = Union[str, ObjectId]


def _users():
    return get_collection(USERS_COLLECTION)


def _notes():
    return get_collection(NOTES_COLLECTION)


def _posts():
    return get_collection(POSTS_COLLECTION)


def _attempts():
    return get_collection(LOGIN_ATTEMPTS_COLLECTION)


def _pick(data: dict, allowed: tuple) -> dict:
    changes = {key: data[key] for key in allowed if key in data}
    if not changes:
        raise ValidationError({"non_field_errors": ["No valid fields to update."]})
    return changes


def _title_filter(search: str) -> dict:
    # re.escape means the client can never inject its own regex.
    return {"$regex": re.escape(search.strip()), "$options": "i"}


def _sort_spec(ordering: str) -> list:
    direction = DESCENDING if ordering.startswith("-") else ASCENDING
    # _id as tie breaker keeps pages stable and lets the index serve the sort.
    return [(ordering.lstrip("-"), direction), ("_id", direction)]


def _paginate(collection, query: dict, *, ordering: str, page: int, page_size: int,
              projection=None) -> tuple[list[dict], int]:
    total = collection.count_documents(query, maxTimeMS=QUERY_TIMEOUT_MS)
    cursor = (
        collection.find(query, projection)
        .sort(_sort_spec(ordering))
        .skip((page - 1) * page_size)
        .limit(page_size)
        .max_time_ms(QUERY_TIMEOUT_MS)
    )
    return list(cursor), total


# ----------------------------------------------------------------------- users
def register_user(data: dict) -> dict:
    """Public registration. The role is never read from the input, so it is
    always the default one. Uniqueness is enforced by the unique indexes."""
    document = new_user_document(
        username=data["username"],
        email=data["email"],
        password_hash=hash_password(data["password"]),
        full_name=data["full_name"],
        interests=data.get("interests", []),
    )
    try:
        _users().insert_one(document)
    except DuplicateKeyError as exc:
        raise conflict_from_duplicate_key(exc) from exc

    document.pop("password")
    return document


# ------------------------------------------------------------ brute force guard
def _raise_if_locked(keys: list[str]) -> None:
    now = utc_now()
    locked = _attempts().find_one(
        {"key": {"$in": keys}, "locked_until": {"$gt": now}},
        {"locked_until": 1},
        sort=[("locked_until", DESCENDING)],
    )
    if locked:
        wait = math.ceil((locked["locked_until"] - now).total_seconds())
        raise TooManyAttempts(wait=max(wait, 1))


def _record_hit(key: str, limit: int) -> None:
    """Count one hit for `key` and start a lockout when `limit` is reached.

    The counter is a fixed window. $inc is atomic, so parallel requests are
    all counted. If the window is over, the document is reset (or created).
    """
    now = utc_now()
    window_end = now + timedelta(seconds=settings.AUTH_ATTEMPT_WINDOW_SECONDS)
    attempts = _attempts()

    doc = attempts.find_one_and_update(
        {"key": key, "window_ends_at": {"$gt": now}},
        {"$inc": {"count": 1}},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        fresh = {
            "count": 1,
            "window_ends_at": window_end,
            "expires_at": window_end,
            "locked_until": None,
        }
        try:
            doc = attempts.find_one_and_update(
                {"key": key}, {"$set": fresh}, upsert=True, return_document=ReturnDocument.AFTER
            )
        except DuplicateKeyError:
            # another request created the document a moment earlier
            doc = attempts.find_one_and_update(
                {"key": key}, {"$inc": {"count": 1}}, return_document=ReturnDocument.AFTER
            )

    if doc and doc["count"] >= limit:
        locked_until = now + timedelta(seconds=settings.AUTH_LOCKOUT_SECONDS)
        attempts.update_one(
            {"key": key},
            {"$set": {
                "locked_until": locked_until,
                "expires_at": max(locked_until, doc["window_ends_at"]),
            }},
        )
        logger.warning("Auth lockout started (scope=%s)", key.split(":", 1)[0])


def _enforce_rate_limit(*rules: tuple[str, int]) -> None:
    _raise_if_locked([key for key, _ in rules])
    for key, limit in rules:
        _record_hit(key, limit)


def authenticate_user(email: str, password: str, ip: str) -> dict:
    """Check credentials. A wrong password and an unknown email look the same
    (same message, same amount of hashing work)."""
    email_key, ip_key = f"email:{email}", f"ip:{ip}"
    _raise_if_locked([email_key, ip_key])

    user = _users().find_one({"email": email})
    if user is None:
        dummy_password_check(password)
        password_ok = False
    else:
        password_ok = verify_password(password, user.get("password"))

    if not password_ok:
        _record_hit(email_key, settings.LOGIN_MAX_ATTEMPTS_PER_EMAIL)
        _record_hit(ip_key, settings.LOGIN_MAX_ATTEMPTS_PER_IP)
        logger.info("Failed login attempt from %s", ip)
        raise InvalidCredentials()

    if not user.get("is_active", False):
        # Only reached with the right password, so this reveals nothing to a guesser.
        raise PermissionDenied("This account has been deactivated.")

    _attempts().delete_one({"key": email_key})
    user.pop("password", None)
    return user


# -------------------------------------------------------------- password reset
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _send_reset_email(email: str, token: str) -> None:
    link = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password?token={token}"
    body = (
        "We received a request to reset your NoteSphere password.\n\n"
        f"Open this link to choose a new password:\n{link}\n\n"
        f"The link works once and expires in {settings.PASSWORD_RESET_TOKEN_LIFETIME} minutes. "
        "If you did not ask for this, you can ignore this email."
    )
    try:
        send_mail("Reset your NoteSphere password", body, settings.DEFAULT_FROM_EMAIL, [email])
    except Exception:
        # The client always gets the same answer, so a mail failure is only logged.
        logger.exception("Could not send password reset email")


def request_password_reset(email: str, ip: str) -> None:
    """Always returns normally, whether the email exists or not."""
    _enforce_rate_limit(
        (f"reset-email:{email}", settings.PASSWORD_RESET_MAX_REQUESTS),
        (f"reset-ip:{ip}", settings.PASSWORD_RESET_MAX_REQUESTS_PER_IP),
    )

    user = _users().find_one({"email": email, "is_active": True}, {"_id": 1})
    if user is None:
        return

    now = utc_now()
    resets = get_collection(PASSWORD_RESETS_COLLECTION)
    resets.update_many(
        {"user_id": user["_id"], "used": False},
        {"$set": {"used": True, "invalidated_at": now}},
    )

    token = secrets.token_urlsafe(32)
    resets.insert_one({
        "user_id": user["_id"],
        "token_hash": _hash_token(token),  # only the hash is stored
        "used": False,
        "created_at": now,
        "expires_at": now + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_LIFETIME),
    })
    _send_reset_email(email, token)


def reset_password(token: str, new_password: str) -> None:
    now = utc_now()
    # Claiming the token is one atomic step, so it can only be used once even
    # if two requests arrive together.
    record = get_collection(PASSWORD_RESETS_COLLECTION).find_one_and_update(
        {"token_hash": _hash_token(token), "used": False, "expires_at": {"$gt": now}},
        {"$set": {"used": True, "used_at": now}},
    )
    invalid = ValidationError({"token": ["Invalid or expired reset token."]})
    if record is None:
        raise invalid

    result = _users().update_one(
        {"_id": record["user_id"], "is_active": True},
        {"$set": {"password": hash_password(new_password), "updated_at": now}},
    )
    if result.matched_count == 0:
        raise invalid
    revoke_all_user_tokens(record["user_id"])


# ----------------------------------------------------------------------- notes
def create_note(user_id: ObjectId, data: dict) -> dict:
    fields = {key: data[key] for key in NOTE_EDITABLE_FIELDS if key in data}
    document = new_note_document(user_id=user_id, **fields)
    _notes().insert_one(document)
    return document


def list_notes(user, params: dict) -> tuple[list[dict], int]:
    query = ownership_filter(user)
    if is_admin(user) and "user_id" in params:
        query["user_id"] = params["user_id"]
    if params.get("search"):
        query["title"] = _title_filter(params["search"])
    for flag in ("is_pinned", "is_archived"):
        if flag in params:
            query[flag] = params[flag]

    return _paginate(
        _notes(), query,
        ordering=params["ordering"], page=params["page"], page_size=params["page_size"],
    )


def get_note(user, note_id: DocumentId) -> dict:
    note = _notes().find_one({"_id": to_object_id(note_id), **ownership_filter(user)})
    if note is None:
        raise NotFound("Note not found.")
    return note


def update_note(user, note_id: DocumentId, data: dict) -> dict:
    changes = _pick(data, NOTE_EDITABLE_FIELDS)
    changes["updated_at"] = utc_now()
    # Ownership is part of the filter, so the check and the write are one atomic step.
    note = _notes().find_one_and_update(
        {"_id": to_object_id(note_id), **ownership_filter(user)},
        {"$set": changes},
        return_document=ReturnDocument.AFTER,
    )
    if note is None:
        raise NotFound("Note not found.")
    return note


def delete_note(user, note_id: DocumentId) -> None:
    result = _notes().delete_one({"_id": to_object_id(note_id), **ownership_filter(user)})
    if result.deleted_count == 0:
        raise NotFound("Note not found.")


# ----------------------------------------------------------------------- posts
def create_post(user_id: ObjectId, data: dict) -> dict:
    fields = {key: data[key] for key in POST_EDITABLE_FIELDS if key in data}
    document = new_post_document(user_id=user_id, **fields)
    _posts().insert_one(document)
    return document


def list_posts(user, params: dict) -> tuple[list[dict], int]:
    """Everyone gets published posts only. An admin sees every post unless
    they pass ?is_published=true|false."""
    query: dict = {}
    if is_admin(user):
        if "is_published" in params:
            query["is_published"] = params["is_published"]
    else:
        query["is_published"] = True

    if params.get("search"):
        query["title"] = _title_filter(params["search"])
    if params.get("tag"):
        tags = normalize_string_list([params["tag"]])
        if tags:
            query["tags"] = tags[0]

    return _paginate(
        _posts(), query,
        ordering=params["ordering"], page=params["page"], page_size=params["page_size"],
        projection={"content": 0},
    )


def get_post(post_id: DocumentId) -> dict:
    post = _posts().find_one({"_id": to_object_id(post_id)})
    if post is None:
        raise NotFound("Post not found.")
    return post


def update_post(post_id: DocumentId, user, data: dict) -> dict:
    changes = _pick(data, POST_EDITABLE_FIELDS)
    now = utc_now()

    # Pipeline style update, so published_at can depend on the stored value in
    # the same atomic write. Client values go through $literal, otherwise a
    # string starting with "$" would be evaluated as an expression.
    stage = {key: {"$literal": value} for key, value in changes.items()}
    stage["updated_at"] = now
    if "is_published" in changes:
        if changes["is_published"]:
            stage["published_at"] = {
                "$cond": [
                    {"$eq": ["$is_published", True]},
                    {"$ifNull": ["$published_at", now]},
                    now,
                ]
            }
        else:
            stage["published_at"] = None

    post = _posts().find_one_and_update(
        {"_id": to_object_id(post_id), **ownership_filter(user)},
        [{"$set": stage}],
        return_document=ReturnDocument.AFTER,
    )
    if post is None:
        raise NotFound("Post not found.")
    return post


def delete_post(post_id: DocumentId, user) -> None:
    result = _posts().delete_one({"_id": to_object_id(post_id), **ownership_filter(user)})
    if result.deleted_count == 0:
        raise NotFound("Post not found.")


# ---------------------------------------------------------------- aggregations
def group_users_by_interest(page: int, page_size: int) -> tuple[list[dict], int]:
    """Scenario 1. One aggregate() call does the grouping and the pagination.

    $unwind drops users with an empty interests array, and the $match in front
    avoids unwinding them at all. Only a small allowlist of user fields is
    pushed, so the password hash can never end up in the result.
    """
    skip = (page - 1) * page_size
    pipeline = [
        {"$match": {"interests.0": {"$exists": True}}},
        {"$unwind": "$interests"},
        {"$group": {
            "_id": "$interests",
            "user_count": {"$sum": 1},
            "users": {"$push": {
                "_id": "$_id",
                "username": "$username",
                "full_name": "$full_name",
                "profile_image": "$profile_image",
            }},
        }},
        {"$sort": {"user_count": -1, "_id": 1}},
        {"$facet": {
            "groups": [
                {"$skip": skip},
                {"$limit": page_size},
                {"$project": {"_id": 0, "interest": "$_id", "user_count": 1, "users": 1}},
            ],
            "total": [{"$count": "count"}],
        }},
    ]
    result = list(_users().aggregate(pipeline, allowDiskUse=True, maxTimeMS=QUERY_TIMEOUT_MS))
    facet = result[0] if result else {"groups": [], "total": []}
    total = facet["total"][0]["count"] if facet["total"] else 0
    return facet["groups"], total


def get_user_with_posts(user_id: DocumentId, requester, page: int, page_size: int) -> tuple[dict, int]:
    """Scenario 2. A single pipeline: match the user, $lookup their posts
    (filtered, sorted and paginated inside the lookup) and shape the output.

    Visitors only get published posts of active users. The owner and admins
    also get drafts, and admins can open inactive users.
    """
    uid = to_object_id(user_id, "user_id")
    skip = (page - 1) * page_size

    user_match: dict = {"_id": uid}
    if not is_admin(requester):
        user_match["is_active"] = True

    post_match: dict = {"$expr": {"$eq": ["$user_id", "$$uid"]}}
    if not can_view_unpublished_posts(requester, uid):
        post_match["is_published"] = True

    pipeline = [
        {"$match": user_match},
        {"$lookup": {
            "from": POSTS_COLLECTION,
            "let": {"uid": "$_id"},
            "pipeline": [
                {"$match": post_match},
                {"$sort": {"created_at": -1, "_id": -1}},
                {"$project": {"content": 0}},
                {"$facet": {
                    "items": [{"$skip": skip}, {"$limit": page_size}],
                    "total": [{"$count": "count"}],
                }},
            ],
            "as": "post_page",
        }},
        # $facet always returns exactly one document, so a user without posts
        # still survives the unwind (items = [], total = 0).
        {"$unwind": "$post_page"},
        {"$project": {
            "username": 1,
            "full_name": 1,
            "bio": 1,
            "interests": 1,
            "profile_image": 1,
            "cover_image": 1,
            "location": 1,
            "website": 1,
            "created_at": 1,
            "posts": "$post_page.items",
            "posts_total": {"$ifNull": [{"$arrayElemAt": ["$post_page.total.count", 0]}, 0]},
        }},
    ]
    result = list(_users().aggregate(pipeline, maxTimeMS=QUERY_TIMEOUT_MS))
    if not result:
        raise NotFound("User not found.")

    profile = result[0]
    total = profile.pop("posts_total")
    return profile, total
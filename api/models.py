from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from bson import ObjectId

from .exceptions import InvalidObjectId

# ---------------------------------------------------------------- collections
USERS_COLLECTION = "users"
NOTES_COLLECTION = "notes"
POSTS_COLLECTION = "posts"
REFRESH_TOKENS_COLLECTION = "refresh_tokens"
PASSWORD_RESETS_COLLECTION = "password_resets"
LOGIN_ATTEMPTS_COLLECTION = "login_attempts"

# ---------------------------------------------------------------------- roles
ROLE_USER = "user"
ROLE_ADMIN = "admin"
ROLES = (ROLE_USER, ROLE_ADMIN)

# --------------------------------------------------------------------- limits
USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 30
EMAIL_MAX_LENGTH = 254
FULL_NAME_MAX_LENGTH = 100
BIO_MAX_LENGTH = 500
LOCATION_MAX_LENGTH = 100
URL_MAX_LENGTH = 500
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128  # long inputs make Argon2 expensive, so cap it

MAX_INTERESTS = 20
INTEREST_MAX_LENGTH = 30
MAX_TAGS = 10
TAG_MAX_LENGTH = 30

NOTE_TITLE_MAX_LENGTH = 200
NOTE_CONTENT_MAX_LENGTH = 20_000
NOTE_COLORS = ("default", "yellow", "green", "blue", "pink", "purple", "orange", "gray")

POST_TITLE_MAX_LENGTH = 200
POST_SUMMARY_MAX_LENGTH = 300
POST_CONTENT_MAX_LENGTH = 50_000

SEARCH_MAX_LENGTH = 100
DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100
MAX_PAGE = 10_000

# ------------------------------------------------------- allowlisted fields
# Only these keys may ever reach a $set operator. Anything else is dropped.
USER_PROFILE_FIELDS = (
    "full_name",
    "bio",
    "interests",
    "profile_image",
    "cover_image",
    "location",
    "website",
)
USER_SELF_EDITABLE_FIELDS = ("username",) + USER_PROFILE_FIELDS
USER_ADMIN_EDITABLE_FIELDS = USER_SELF_EDITABLE_FIELDS + (
    "email",
    "password",
    "role",
    "is_active",
    "is_verified",
)
USER_ADMIN_CREATE_FIELDS = USER_PROFILE_FIELDS + ("role", "is_active", "is_verified")

NOTE_EDITABLE_FIELDS = ("title", "content", "color", "tags", "is_pinned", "is_archived")
POST_EDITABLE_FIELDS = (
    "title",
    "content",
    "summary",
    "cover_image",
    "tags",
    "is_published",
)


# -------------------------------------------------------------------- helpers
def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_object_id(value: Any, field: str = "id") -> ObjectId:
    """Return an ObjectId or raise a 400 error. Never lets junk reach a query."""
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and len(value) == 24 and ObjectId.is_valid(value):
        return ObjectId(value)
    raise InvalidObjectId(field)


def normalize_string_list(values: Iterable[str]) -> list[str]:
    """Lowercase, trim, collapse spaces and drop duplicates (keeps the order)."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        item = " ".join(str(value).split()).lower()
        if item and item not in seen:
            seen.add(item)
            cleaned.append(item)
    return cleaned


# ------------------------------------------------------------ document builders
def new_user_document(
    *,
    username: str,
    email: str,
    password_hash: str,
    full_name: str = "",
    role: str = ROLE_USER,
    interests: Optional[list[str]] = None,
    bio: str = "",
    profile_image: str = "",
    cover_image: str = "",
    location: str = "",
    website: str = "",
    is_active: bool = True,
    is_verified: bool = False,
) -> dict:
    now = utc_now()
    return {
        "username": username,
        "full_name": full_name,
        "email": email,
        "password": password_hash,
        "role": role,
        "interests": interests or [],
        "bio": bio,
        "profile_image": profile_image,
        "cover_image": cover_image,
        "location": location,
        "website": website,
        "is_active": is_active,
        "is_verified": is_verified,
        "created_at": now,
        "updated_at": now,
    }


def new_note_document(
    *,
    user_id: ObjectId,
    title: str,
    content: str,
    color: str = "default",
    tags: Optional[list[str]] = None,
    is_pinned: bool = False,
    is_archived: bool = False,
) -> dict:
    now = utc_now()
    return {
        "user_id": user_id,
        "title": title,
        "content": content,
        "color": color,
        "tags": tags or [],
        "is_pinned": is_pinned,
        "is_archived": is_archived,
        "created_at": now,
        "updated_at": now,
    }


def new_post_document(
    *,
    user_id: ObjectId,
    title: str,
    content: str,
    summary: str = "",
    cover_image: str = "",
    tags: Optional[list[str]] = None,
    is_published: bool = False,
) -> dict:
    now = utc_now()
    return {
        "user_id": user_id,
        "title": title,
        "summary": summary,
        "content": content,
        "cover_image": cover_image,
        "tags": tags or [],
        "is_published": is_published,
        "published_at": now if is_published else None,
        "created_at": now,
        "updated_at": now,
    }
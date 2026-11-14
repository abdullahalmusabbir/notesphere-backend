from typing import Optional

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, IndexModel

from db_connection import get_collection, get_database

from .models import (
    LOGIN_ATTEMPTS_COLLECTION,
    NOTES_COLLECTION,
    PASSWORD_RESETS_COLLECTION,
    POSTS_COLLECTION,
    REFRESH_TOKENS_COLLECTION,
    USERS_COLLECTION,
)

INDEXES: dict[str, list[IndexModel]] = {
    USERS_COLLECTION: [
        # Login and forgot-password do find_one({"email": ...}). Also makes
        # duplicate emails impossible, even for two parallel registrations.
        IndexModel([("email", ASCENDING)], name="uniq_email", unique=True),
        # Same for usernames. The admin search by username prefix uses it too.
        IndexModel([("username", ASCENDING)], name="uniq_username", unique=True),
        # Admin user list: sort by created_at with _id as tie breaker, then
        # skip/limit. Also works for the oldest-first order (reverse scan).
        IndexModel([("created_at", DESCENDING), ("_id", DESCENDING)], name="created_at_id_desc"),
    ],
    NOTES_COLLECTION: [
        # "My notes" list: filter by user_id, sorted by created_at, paginated.
        # The user_id prefix also serves single user filters and counts.
        IndexModel(
            [("user_id", ASCENDING), ("created_at", DESCENDING), ("_id", DESCENDING)],
            name="user_created_at_id",
        ),
    ],
    POSTS_COLLECTION: [
        # Scenario 2: the $lookup matches posts.user_id and sorts by created_at.
        # The user_id prefix is the index the lookup needs.
        IndexModel(
            [("user_id", ASCENDING), ("created_at", DESCENDING), ("_id", DESCENDING)],
            name="user_created_at_id",
        ),
        # Public feed: find({"is_published": True}) sorted by created_at.
        # Partial, so drafts are not stored in it and it stays small.
        IndexModel(
            [("created_at", DESCENDING), ("_id", DESCENDING)],
            name="published_feed",
            partialFilterExpression={"is_published": True},
        ),
    ],
    REFRESH_TOKENS_COLLECTION: [
        # Every refresh and logout looks the token up by its jti.
        IndexModel([("jti", ASCENDING)], name="uniq_jti", unique=True),
        # revoke_all_user_tokens() filters by user_id (password change,
        # role change, reuse detection). Without it that is a full scan.
        IndexModel([("user_id", ASCENDING)], name="user_id"),
        # Expired tokens are useless, so MongoDB removes them automatically.
        IndexModel([("expires_at", ASCENDING)], name="ttl_expires_at", expireAfterSeconds=0),
    ],
    PASSWORD_RESETS_COLLECTION: [
        # reset-password claims the token by its hash.
        IndexModel([("token_hash", ASCENDING)], name="uniq_token_hash", unique=True),
        IndexModel([("expires_at", ASCENDING)], name="ttl_expires_at", expireAfterSeconds=0),
    ],
    LOGIN_ATTEMPTS_COLLECTION: [
        # Every login and reset request reads/updates the counter by key.
        IndexModel([("key", ASCENDING)], name="uniq_key", unique=True),
        # Old counters and finished lockouts clean themselves up.
        IndexModel([("expires_at", ASCENDING)], name="ttl_expires_at", expireAfterSeconds=0),
    ],
}


def ensure_indexes() -> dict[str, list[str]]:
    created = {}
    for collection_name, indexes in INDEXES.items():
        created[collection_name] = get_collection(collection_name).create_indexes(indexes)
    return created


def _index_names(plan) -> list[str]:
    names: list[str] = []
    if isinstance(plan, dict):
        for key, value in plan.items():
            if key == "indexName":
                names.append(value)
            else:
                names.extend(_index_names(value))
    elif isinstance(plan, list):
        for item in plan:
            names.extend(_index_names(item))
    return names


def _explain_find(collection: str, filter_: dict, sort: Optional[dict] = None) -> dict:
    command: dict = {"find": collection, "filter": filter_, "limit": 10}
    if sort:
        command["sort"] = sort
    result = get_database().command({"explain": command, "verbosity": "executionStats"})
    stats = result["executionStats"]
    return {
        "indexes_used": sorted(set(_index_names(result["queryPlanner"]["winningPlan"]))),
        "keys_examined": stats["totalKeysExamined"],
        "docs_examined": stats["totalDocsExamined"],
        "returned": stats["nReturned"],
        "time_ms": stats["executionTimeMillis"],
    }


def explain_key_queries() -> dict:
    """explain("executionStats") for the main queries. An empty
    `indexes_used` means that query does a collection scan."""
    sample_user = ObjectId()
    newest_first = {"created_at": -1, "_id": -1}
    return {
        "user_by_email": _explain_find(USERS_COLLECTION, {"email": "someone@example.com"}),
        "admin_user_listing": _explain_find(USERS_COLLECTION, {}, newest_first),
        "user_notes_listing": _explain_find(NOTES_COLLECTION, {"user_id": sample_user}, newest_first),
        "user_posts_lookup": _explain_find(
            POSTS_COLLECTION, {"user_id": sample_user, "is_published": True}, newest_first
        ),
        "public_posts_feed": _explain_find(POSTS_COLLECTION, {"is_published": True}, newest_first),
    }
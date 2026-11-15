import os
import secrets
from datetime import timedelta
from functools import lru_cache
from typing import Any

import jwt
from bson import ObjectId
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ImproperlyConfigured
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from db_connection import get_collection

from .models import (
    REFRESH_TOKENS_COLLECTION,
    ROLE_ADMIN,
    ROLE_USER,
    USERS_COLLECTION,
    utc_now,
)

ALGORITHM = "HS256"
ISSUER = "notesphere"
ACCESS_TOKEN = "access"
REFRESH_TOKEN = "refresh"
MAX_TOKEN_LENGTH = 2048


# ------------------------------------------------------------------ passwords
def hash_password(raw_password: str) -> str:
    return make_password(raw_password)


def verify_password(raw_password: Any, encoded: Any) -> bool:
    if not isinstance(raw_password, str) or not isinstance(encoded, str):
        return False
    return check_password(raw_password, encoded)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return hash_password(secrets.token_urlsafe(16))


def dummy_password_check(raw_password: str) -> None:
    """Burn the same time as a real check when the email does not exist,
    so response time does not reveal which emails are registered."""
    verify_password(raw_password, _dummy_hash())


# ------------------------------------------------------------------- settings
def _signing_key() -> str:
    key = os.getenv("JWT_SECRET_KEY", "")
    if len(key) < 32:
        raise ImproperlyConfigured("JWT_SECRET_KEY must be set and at least 32 characters long.")
    return key


def access_lifetime() -> timedelta:
    return timedelta(minutes=int(os.getenv("JWT_ACCESS_TOKEN_LIFETIME", "15")))


def refresh_lifetime() -> timedelta:
    return timedelta(days=int(os.getenv("JWT_REFRESH_TOKEN_LIFETIME", "7")))


# --------------------------------------------------------------------- tokens
def _encode(user_id: ObjectId, token_type: str, lifetime: timedelta):
    issued_at = utc_now()
    expires_at = issued_at + lifetime
    jti = secrets.token_hex(16)
    payload = {
        "iss": ISSUER,
        "sub": str(user_id),
        "type": token_type,
        "jti": jti,
        "iat": issued_at,
        "exp": expires_at,
    }
    token = jwt.encode(payload, _signing_key(), algorithm=ALGORITHM)
    return token, jti, issued_at, expires_at


def create_access_token(user_id: ObjectId) -> str:
    token, *_ = _encode(user_id, ACCESS_TOKEN, access_lifetime())
    return token


def create_refresh_token(user_id: ObjectId) -> str:
    token, jti, issued_at, expires_at = _encode(user_id, REFRESH_TOKEN, refresh_lifetime())
    get_collection(REFRESH_TOKENS_COLLECTION).insert_one(
        {
            "jti": jti,
            "user_id": user_id,
            "revoked": False,
            "created_at": issued_at,
            "expires_at": expires_at,
        }
    )
    return token


def issue_token_pair(user_id: ObjectId) -> dict:
    return {
        "access": create_access_token(user_id),
        "refresh": create_refresh_token(user_id),
        "token_type": "Bearer",
        "expires_in": int(access_lifetime().total_seconds()),
    }


def decode_token(token: str, expected_type: str) -> dict:
    if not token or len(token) > MAX_TOKEN_LENGTH:
        raise AuthenticationFailed("Invalid token.")
    try:
        payload = jwt.decode(
            token,
            _signing_key(),
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "jti", "type"]},
        )
    except jwt.ExpiredSignatureError:
        raise AuthenticationFailed("Token has expired.")
    except jwt.InvalidTokenError:
        raise AuthenticationFailed("Invalid token.")

    if payload.get("type") != expected_type:
        raise AuthenticationFailed("Invalid token.")
    return payload


def _subject_id(payload: dict) -> ObjectId:
    subject = payload.get("sub")
    if not isinstance(subject, str) or not ObjectId.is_valid(subject):
        raise AuthenticationFailed("Invalid token.")
    return ObjectId(subject)


def _find_active_user(user_id: ObjectId) -> dict:
    user = get_collection(USERS_COLLECTION).find_one(
        {"_id": user_id, "is_active": True}, {"password": 0}
    )
    if user is None:
        raise AuthenticationFailed("Account is inactive or does not exist.")
    return user


# ----------------------------------------------------------- refresh / revoke
def revoke_all_user_tokens(user_id: ObjectId) -> None:
    get_collection(REFRESH_TOKENS_COLLECTION).update_many(
        {"user_id": user_id, "revoked": False},
        {"$set": {"revoked": True, "revoked_at": utc_now()}},
    )


def rotate_refresh_token(token: str) -> tuple[dict, dict]:
    """Exchange a refresh token for a new pair and return (user, tokens).

    The old token is claimed with one atomic find_one_and_update, so two
    requests with the same token can never both succeed. If a token that was
    already used shows up again it is treated as stolen and every session of
    that user is revoked.
    """
    payload = decode_token(token, REFRESH_TOKEN)
    user_id = _subject_id(payload)
    tokens = get_collection(REFRESH_TOKENS_COLLECTION)

    claimed = tokens.find_one_and_update(
        {"jti": payload["jti"], "user_id": user_id, "revoked": False},
        {"$set": {"revoked": True, "revoked_at": utc_now()}},
    )
    if claimed is None:
        if tokens.find_one({"jti": payload["jti"], "user_id": user_id}, {"_id": 1}):
            revoke_all_user_tokens(user_id)
        raise AuthenticationFailed("Invalid token.")

    user = _find_active_user(user_id)
    return user, issue_token_pair(user_id)


def revoke_refresh_token(token: str, user_id: ObjectId) -> None:
    """Logout. Safe to call twice; the second call simply changes nothing."""
    payload = decode_token(token, REFRESH_TOKEN)
    if _subject_id(payload) != user_id:
        raise AuthenticationFailed("Invalid token.")
    get_collection(REFRESH_TOKENS_COLLECTION).update_one(
        {"jti": payload["jti"], "user_id": user_id, "revoked": False},
        {"$set": {"revoked": True, "revoked_at": utc_now()}},
    )


# ---------------------------------------------------------------- DRF classes
class AuthUser:
    """What `request.user` is for every authenticated request.

    Built from the database document on each request, so a role change or a
    deactivation takes effect immediately, not when the token expires.
    """

    is_authenticated = True
    is_anonymous = False

    def __init__(self, document: dict):
        self.document = document
        self.id: ObjectId = document["_id"]
        self.pk = self.id
        self.username = document.get("username")
        self.email = document.get("email")
        self.role = document.get("role", ROLE_USER)

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    def __str__(self) -> str:
        return str(self.username)


class JWTAuthentication(BaseAuthentication):
    keyword = b"bearer"

    def authenticate(self, request):
        header = get_authorization_header(request).split()
        if not header or header[0].lower() != self.keyword:
            return None
        if len(header) != 2:
            raise AuthenticationFailed("Invalid authorization header.")

        try:
            token = header[1].decode("ascii")
        except UnicodeError:
            raise AuthenticationFailed("Invalid authorization header.")

        payload = decode_token(token, ACCESS_TOKEN)
        user = _find_active_user(_subject_id(payload))
        return AuthUser(user), payload

    def authenticate_header(self, request) -> str:
        # Makes DRF answer 401 (not 403) when authentication is missing.
        return 'Bearer realm="api"'
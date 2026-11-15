import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import RequestDataTooBig
from django.http import Http404
from pymongo.errors import ConnectionFailure, DuplicateKeyError, PyMongoError
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    NotFound,
    ParseError,
    PermissionDenied,
    Throttled,
    ValidationError,
)
from rest_framework.response import Response

logger = logging.getLogger("api")


class ConflictError(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Resource already exists."
    default_code = "conflict"

    def __init__(self, detail=None, errors=None):
        super().__init__(detail)
        self.errors = errors or {}


class PayloadTooLarge(APIException):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    default_detail = "Request body is too large."
    default_code = "payload_too_large"


class InvalidObjectId(ValidationError):
    def __init__(self, field: str = "id"):
        super().__init__({field: ["Invalid identifier."]})


class InvalidCredentials(AuthenticationFailed):
    """Same message for a wrong password and an unknown email."""

    default_detail = "Invalid email or password."
    default_code = "invalid_credentials"


class TooManyAttempts(Throttled):
    default_detail = "Too many failed attempts. Please try again later."
    default_code = "too_many_attempts"


def conflict_from_duplicate_key(exc: DuplicateKeyError) -> ConflictError:
    """Turn a unique-index violation into a readable 409 response."""
    details = getattr(exc, "details", None) or {}
    key_pattern = details.get("keyPattern") or {}
    message = str(details.get("errmsg", ""))

    for field in ("email", "username"):
        if field in key_pattern or f"dup key: {{ {field}:" in message:
            return ConflictError(
                f"A user with this {field} already exists.",
                {field: [f"This {field} is already in use."]},
            )
    return ConflictError()


def _error_response(status_code: int, message: str, errors=None, headers=None) -> Response:
    body = {"success": False, "message": message, "errors": errors or {}}
    return Response(body, status=status_code, headers=headers)


def _validation_errors(detail) -> dict:
    if isinstance(detail, dict):
        return detail
    return {"non_field_errors": detail}


def custom_exception_handler(exc, context):
    view_name = context["view"].__class__.__name__ if context.get("view") else "unknown"

    if isinstance(exc, Http404):
        exc = NotFound("Resource not found.")
    elif isinstance(exc, DjangoPermissionDenied):
        exc = PermissionDenied()
    elif isinstance(exc, RequestDataTooBig):
        exc = PayloadTooLarge()
    elif isinstance(exc, DuplicateKeyError):
        exc = conflict_from_duplicate_key(exc)
    elif isinstance(exc, ConnectionFailure):
        logger.error("Database unavailable in %s", view_name, exc_info=exc)
        return _error_response(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Service temporarily unavailable. Please try again later.",
        )
    elif isinstance(exc, PyMongoError):
        logger.error("Database error in %s", view_name, exc_info=exc)
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Something went wrong."
        )

    if isinstance(exc, APIException):
        headers = {}
        if getattr(exc, "auth_header", None):
            headers["WWW-Authenticate"] = exc.auth_header
        if getattr(exc, "wait", None):
            headers["Retry-After"] = str(exc.wait)

        if isinstance(exc, ValidationError):
            return _error_response(
                exc.status_code,
                "Validation failed.",
                _validation_errors(exc.detail),
                headers,
            )
        if isinstance(exc, ParseError):
            # DRF's own parse message contains parser internals, so hide it.
            return _error_response(exc.status_code, "Malformed request body.", headers=headers)

        return _error_response(
            exc.status_code, str(exc.detail), getattr(exc, "errors", None), headers
        )

    logger.error("Unhandled exception in %s", view_name, exc_info=exc)
    return _error_response(status.HTTP_500_INTERNAL_SERVER_ERROR, "Something went wrong.")
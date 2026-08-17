"""Stable JSON error envelopes and the exception-to-response mapper.

The envelope is always ``{"error": {"code", "message", "fields"}}`` where
``fields`` is ``{}`` or a field-keyed mapping of messages. No tracebacks,
exception class names, SQL errors, or internal details leak.
"""

from rest_framework import status
from rest_framework.exceptions import (
    AuthenticationFailed,
    NotAuthenticated,
    ValidationError,
)
from rest_framework.response import Response

from inventory.ai.exceptions import (
    AIConfigError,
    AIMalformedOutputError,
    AIOutputTooLargeError,
    AIProviderError,
    AIRequestError,
)
from inventory.exceptions import (
    AllocationMismatch,
    DuplicateMealEvent,
    HouseholdMismatch,
    InvalidAdjustment,
    InvalidQuantity,
    InvalidUnit,
    InsufficientStock,
    SuggestionNotCookable,
    UnitMismatch,
)


def error_response(code, message, fields=None, http_status=status.HTTP_400_BAD_REQUEST):
    """Build the stable error envelope response."""
    return Response(
        {
            "error": {
                "code": code,
                "message": message,
                "fields": fields or {},
            }
        },
        status=http_status,
    )


def not_found_response(message="Resource not found."):
    return error_response("not_found", message, http_status=status.HTTP_404_NOT_FOUND)


def csrf_failed_response():
    return error_response(
        "csrf_failed",
        "CSRF verification failed.",
        http_status=status.HTTP_403_FORBIDDEN,
    )


def not_authenticated_response():
    return error_response(
        "not_authenticated",
        "Authentication credentials were not provided.",
        http_status=status.HTTP_403_FORBIDDEN,
    )


def validation_response(serializer):
    """Build the stable validation error envelope from a DRF serializer."""
    fields = {}
    for key, messages in serializer.errors.items():
        if isinstance(messages, list):
            fields[key] = [str(m) for m in messages]
        else:
            fields[key] = [str(messages)]
    return error_response(
        "validation_error",
        "Request validation failed.",
        fields,
    )


def service_error_response(exc):
    """Map a known InventoryServiceError subclass to a stable envelope.

    Unknown exception types are re-raised so programming errors are never
    silently converted to user-facing 4xx responses.
    """
    if isinstance(exc, HouseholdMismatch):
        return not_found_response()
    if isinstance(exc, InsufficientStock):
        return error_response(
            "insufficient_stock",
            str(exc),
            {"quantity": [str(exc)]},
            http_status=status.HTTP_409_CONFLICT,
        )
    if isinstance(exc, UnitMismatch):
        return error_response(
            "unit_mismatch",
            str(exc),
            {"unit": [str(exc)]},
            http_status=status.HTTP_409_CONFLICT,
        )
    if isinstance(exc, InvalidAdjustment):
        return error_response(
            "no_op_correction",
            str(exc),
            {"observed_balance": [str(exc)]},
            http_status=status.HTTP_409_CONFLICT,
        )
    if isinstance(exc, (InvalidQuantity, InvalidUnit)):
        return error_response(
            "invalid_quantity",
            str(exc),
            {"quantity": [str(exc)]},
        )
    raise exc


def ai_error_response(code, message, http_status):
    """Stable envelope for AI provider failures (no provider internals)."""
    return error_response(code, message, http_status=http_status)


def ai_service_error_response(exc):
    """Map an AIProviderError subclass to a stable envelope.

    Config/timeout/network/HTTP failures are recoverable 503
    ``ai_unavailable``; schema/oversize violations are 422
    ``invalid_provider_output``. Unknown provider exception types are
    re-raised so programming errors are never converted to user errors.
    """
    if isinstance(exc, AIConfigError):
        return error_response(
            "ai_unavailable",
            "The AI provider is not configured on this server.",
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if isinstance(exc, AIRequestError):
        return error_response(
            "ai_unavailable",
            "The AI provider request failed. Please try again.",
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if isinstance(exc, (AIMalformedOutputError, AIOutputTooLargeError)):
        return error_response(
            "invalid_provider_output",
            "The AI provider returned an unusable response.",
            http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    if isinstance(exc, AIProviderError):
        return error_response(
            "ai_unavailable",
            "The AI provider is unavailable.",
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    raise exc


def cook_error_response(exc):
    """Map a confirm_cook InventoryServiceError to a stable envelope.

    Duplicate cook is 409 ``already_cooked``; every other cook-time conflict
    (rejected state, missing stock, stale/insufficient balance, malformed or
    foreign/tampered allocation) is 409 ``cook_conflict``. Unknown exception
    types are re-raised.

    ``HouseholdMismatch`` here means a tampered/foreign allocation under an
    already household-verified suggestion (the view performs its 404 check
    before calling the service), so it maps to the same 409 conflict —
    never to 404.
    """
    if isinstance(exc, DuplicateMealEvent):
        return error_response(
            "already_cooked",
            "This meal has already been cooked.",
            http_status=status.HTTP_409_CONFLICT,
        )
    if isinstance(
        exc,
        (
            HouseholdMismatch,
            SuggestionNotCookable,
            AllocationMismatch,
            InvalidQuantity,
            InvalidUnit,
            UnitMismatch,
            InsufficientStock,
        ),
    ):
        return error_response(
            "cook_conflict",
            "This meal cannot be cooked right now.",
            http_status=status.HTTP_409_CONFLICT,
        )
    raise exc

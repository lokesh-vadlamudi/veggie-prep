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

from inventory.exceptions import (
    HouseholdMismatch,
    InvalidAdjustment,
    InvalidQuantity,
    InvalidUnit,
    InsufficientStock,
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

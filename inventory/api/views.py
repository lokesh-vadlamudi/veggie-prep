"""DRF API views for the inventory endpoints.

Household scoping is always ``request.user.household``; foreign or unknown
household-owned UUIDs are indistinguishable ``404`` for GET and POST. Every
write delegates to :mod:`inventory.services` (service-only writes); views
never create or mutate domain models directly.
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import exceptions as drf_exceptions
from rest_framework import status, viewsets
from rest_framework.response import Response

from inventory import services
from inventory.exceptions import InventoryServiceError
from inventory.models import InventoryEvent, StockLot

from .errors import (
    csrf_failed_response,
    error_response,
    not_found_response,
    not_authenticated_response,
    service_error_response,
    validation_response,
)
from .pagination import ApiPageNumberPagination
from .serializers import (
    AddLotCommandSerializer,
    CorrectLotCommandSerializer,
    LotEventSerializer,
    LotSerializer,
    MutateLotCommandSerializer,
)


def _household(request):
    if not request.user or not request.user.is_authenticated:
        raise drf_exceptions.NotAuthenticated()
    return request.user.household


def _api_exception_handler(exc, context):
    """Stable JSON envelope for DRF exceptions on API paths.

    SessionAuthentication normally returns a bare 403 for anonymous or
    CSRF failures; this handler shapes those into the same envelope as
    every other API error. CSRF and auth failures are read-only: DRF's
    SessionAuthentication enforces them before any view logic runs, so
    no writes occur on these paths.

    Known DRF client exceptions are mapped to stable envelopes with their
    correct status codes; only truly unexpected exceptions become a
    generic 500. Only applies to the ``/api/v1/`` namespace; HTML pages
    keep their usual error behaviour (the handler returns None there).
    """
    view = context.get("view")
    if view is not None:
        # The handler is registered globally but must only shape API errors.
        path = getattr(getattr(view, "request", None), "path", "")
        if not path.startswith("/api/"):
            return None

    if isinstance(exc, drf_exceptions.NotAuthenticated):
        return not_authenticated_response()
    if isinstance(exc, drf_exceptions.PermissionDenied) and "CSRF" in str(exc):
        return csrf_failed_response()
    if isinstance(exc, drf_exceptions.AuthenticationFailed):
        return csrf_failed_response()
    if isinstance(exc, drf_exceptions.MethodNotAllowed):
        response = error_response(
            "method_not_allowed",
            "Method not allowed.",
            http_status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        allow = getattr(exc, "allow", None)
        if allow:
            response.headers["Allow"] = allow
        return response
    if isinstance(exc, drf_exceptions.NotFound):
        return not_found_response()
    if isinstance(exc, drf_exceptions.ValidationError):
        fields = {}
        detail = exc.detail
        if not isinstance(detail, dict):
            detail = {"fields": detail}
        for key, messages in detail.items():
            if isinstance(messages, list):
                fields[key] = [str(m) for m in messages]
            else:
                fields[key] = [str(messages)]
        return error_response("validation_error", "Request validation failed.", fields)
    if isinstance(exc, drf_exceptions.ParseError):
        return error_response(
            "parse_error",
            "Request body could not be parsed.",
            {"body": [str(exc.detail)]},
            http_status=exc.status_code,
        )
    if isinstance(exc, drf_exceptions.UnsupportedMediaType):
        return error_response(
            "unsupported_media_type",
            "Unsupported media type in request.",
            http_status=exc.status_code,
        )
    if isinstance(exc, drf_exceptions.NotAcceptable):
        return error_response(
            "not_acceptable",
            "Could not satisfy the request Accept header.",
            http_status=exc.status_code,
        )
    if isinstance(exc, drf_exceptions.PermissionDenied):
        return error_response(
            "permission_denied",
            "Permission denied.",
            http_status=status.HTTP_403_FORBIDDEN,
        )
    if isinstance(exc, drf_exceptions.APIException):
        # Known DRF client exception type with a stable status: use its
        # own safe detail message; never leak internals.
        detail = exc.detail
        if not isinstance(detail, str):
            detail = "Request could not be processed."
        return error_response(
            "api_error",
            detail,
            http_status=exc.status_code,
        )
    # Unexpected exception on an API path: generic 500 with no detail leak.
    return error_response(
        "internal_error",
        "An unexpected error occurred.",
        http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


class _LotNotFound(Exception):
    """Internal marker for a foreign/unknown lot."""


def _owned_lot(request, pk):
    """404-safe lookup of a lot owned by the request's household."""
    household = _household(request)
    lot = StockLot.objects.filter(pk=pk, household_id=household.pk).first()
    if lot is None:
        raise _LotNotFound()
    return lot


class ValidationError400(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(message)


class LotViewSet(viewsets.GenericViewSet):
    """GET /api/v1/inventory/lots/ and POST /api/v1/inventory/lots/."""

    queryset = StockLot.objects.all()
    serializer_class = LotSerializer
    pagination_class = ApiPageNumberPagination

    def get_lots_filtered(self):
        """Household lots ordered by (created_at, id) with query filters applied.

        Raises :class:`ValidationError400` for invalid filter values.
        Balance filtering is exact (Python ``Decimal`` sums, no float
        aggregation).
        """
        household = _household(self.request)
        lots = list(StockLot.objects.filter(household=household).order_by("created_at", "id"))

        location = self.request.query_params.get("location")
        if location is not None:
            if location not in StockLot.Location.values:
                raise ValidationError400(f"location must be one of {StockLot.Location.values}.")
            lots = [lot for lot in lots if lot.location == location]

        include_empty_param = self.request.query_params.get("include_empty")
        if include_empty_param is None:
            # Default: hide zero-balance lots.
            include_empty = False
        elif include_empty_param == "true":
            include_empty = True
        elif include_empty_param == "false":
            include_empty = False
        else:
            raise ValidationError400("include_empty must be 'true' or 'false'.")
        if not include_empty:
            lots = [lot for lot in lots if services.lot_balance(lot) > 0]

        expiry_group = self.request.query_params.get("expiry_group")
        if expiry_group is not None:
            valid = {"expired", "today", "next_2_days", "later_or_no_date"}
            if expiry_group not in valid:
                raise ValidationError400(f"expiry_group must be one of {sorted(valid)}.")
            today = timezone.localdate()
            buckets = {
                "expired": lambda d: d is not None and d < today,
                "today": lambda d: d == today,
                "next_2_days": lambda d: d is not None and today < d <= today + timedelta(days=2),
                "later_or_no_date": lambda d: d is None or d > today + timedelta(days=2),
            }
            lots = [lot for lot in lots if buckets[expiry_group](lot.expires_on)]
        return lots

    def list(self, request, *args, **kwargs):
        try:
            lots = self.get_lots_filtered()
        except ValidationError400 as exc:
            return error_response("validation_error", exc.message, {"filters": [exc.message]})
        page = self.paginate_queryset(lots)
        return self.get_paginated_response(LotSerializer(page, many=True).data)

    def create(self, request, *args, **kwargs):
        serializer = AddLotCommandSerializer(data=request.data)
        if not serializer.is_valid():
            return validation_response(serializer)
        data = serializer.validated_data
        household = _household(request)
        try:
            with transaction.atomic():
                product = services.resolve_product(
                    household=household,
                    raw_name=data["product_name"],
                    unit=data["unit"],
                )
                lot = services.add_stock(
                    household=household,
                    product=product,
                    quantity=data["quantity"],
                    unit=data["unit"],
                    location=data["location"],
                    purchased_at=data.get("purchased_at"),
                    expires_on=data.get("expires_on"),
                    note=data.get("note") or "",
                )
        except InventoryServiceError as exc:
            return service_error_response(exc)
        response = Response(LotSerializer(lot).data, status=status.HTTP_201_CREATED)
        response.headers["Location"] = f"/api/v1/inventory/lots/{lot.pk}/"
        return response

    def retrieve(self, request, *args, **kwargs):
        try:
            lot = _owned_lot(request, self.kwargs["pk"])
        except _LotNotFound:
            return not_found_response()
        return Response(LotSerializer(lot).data)


class LotEventsView(viewsets.GenericViewSet):
    """GET /api/v1/inventory/lots/<uuid>/events/ — paginated ledger history."""

    serializer_class = LotEventSerializer
    pagination_class = ApiPageNumberPagination
    lookup_field = "pk"

    def list(self, request, pk, *args, **kwargs):
        try:
            lot = _owned_lot(request, pk)
        except _LotNotFound:
            return not_found_response()
        events = InventoryEvent.objects.filter(lot=lot).order_by("created_at", "id")
        page = self.paginate_queryset(events)
        return self.get_paginated_response(LotEventSerializer(page, many=True).data)


class _LotCommandMixin:
    """Shared 404 + service-error plumbing for consume/discard/correct."""

    command_serializer = None

    def _dispatch(self, request, pk, service_call):
        try:
            lot = _owned_lot(request, pk)
        except _LotNotFound:
            return not_found_response()
        serializer = self.command_serializer(data=request.data)
        if not serializer.is_valid():
            return validation_response(serializer)
        data = serializer.validated_data
        household = _household(request)
        try:
            service_call(household, lot, data)
        except InventoryServiceError as exc:
            return service_error_response(exc)
        # Re-fetch after the service transaction so the response reflects
        # the post-mutation ledger state.
        lot.refresh_from_db()
        return Response(LotSerializer(lot).data, status=status.HTTP_200_OK)


class LotConsumeView(_LotCommandMixin, viewsets.GenericViewSet):
    """POST /api/v1/inventory/lots/<uuid>/consume/."""

    command_serializer = MutateLotCommandSerializer

    def post(self, request, pk, *args, **kwargs):
        def call(household, lot, data):
            services.consume_stock(
                household=household,
                lot=lot,
                quantity=data["quantity"],
                unit=lot.unit,
                note=data.get("note") or "",
            )

        return self._dispatch(request, pk, call)


class LotDiscardView(_LotCommandMixin, viewsets.GenericViewSet):
    """POST /api/v1/inventory/lots/<uuid>/discard/."""

    command_serializer = MutateLotCommandSerializer

    def post(self, request, pk, *args, **kwargs):
        def call(household, lot, data):
            services.discard_stock(
                household=household,
                lot=lot,
                quantity=data["quantity"],
                unit=lot.unit,
                note=data.get("note") or "",
            )

        return self._dispatch(request, pk, call)


class LotCorrectView(_LotCommandMixin, viewsets.GenericViewSet):
    """POST /api/v1/inventory/lots/<uuid>/correct/."""

    command_serializer = CorrectLotCommandSerializer

    def post(self, request, pk, *args, **kwargs):
        def call(household, lot, data):
            services.set_lot_balance(
                household=household,
                lot=lot,
                observed_balance=data["observed_balance"],
                note=data["reason"],
            )

        return self._dispatch(request, pk, call)

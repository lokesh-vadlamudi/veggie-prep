"""DRF serializers for the inventory API.

Quantities are exact three-decimal-place strings on the wire. Input accepts
JSON numbers only when they are finite and exact to 3 places (bools are
rejected); output is always an exact string rendered from the ``Decimal``.
No float arithmetic anywhere.
"""

import uuid
from datetime import timedelta, timezone as _dt_timezone
from decimal import Decimal, InvalidOperation

from django.utils import timezone
from rest_framework import serializers

from inventory import services
from inventory.ai import schema as _ai_schema
from inventory.models import (
    InventoryEvent,
    MealIngredient,
    MealSuggestion,
    Product,
    StockLot,
)

THREE_PLACES = Decimal("0.001")
MAX_QUANTITY = Decimal("9999999999.999")  # model max_digits=12, decimal_places=3


def _format_quantity(value) -> str:
    """Render a Decimal as an exact three-decimal string (no floats)."""
    return str(Decimal(value).quantize(THREE_PLACES))


def _to_exact_decimal(value, label="quantity"):
    """Coerce a JSON number/string to an exact 3-place Decimal.

    Rejects bools, non-finite values, and values needing rounding.
    Returns a plain ``Decimal`` (never a float).
    """
    if isinstance(value, bool):
        raise ValueError(f"{label} must not be a boolean.")
    if isinstance(value, Decimal):
        quantity = value
    else:
        try:
            quantity = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError(f"{label} must be a finite decimal number.")
    if not quantity.is_finite():
        raise ValueError(f"{label} must be a finite number.")
    if quantity != quantity.quantize(THREE_PLACES):
        raise ValueError(f"{label} may have at most 3 decimal places.")
    if quantity > MAX_QUANTITY:
        raise ValueError(f"{label} is out of range.")
    return quantity


class ExactDecimalField(serializers.Field):
    """Decimal input accepting JSON numbers/strings, exact to 3 places."""

    def __init__(self, label="quantity", required_positive=False, **kwargs):
        self._label = label
        self._required_positive = required_positive
        kwargs.setdefault("required", True)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        try:
            quantity = _to_exact_decimal(data, self._label)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))
        if self._required_positive and quantity <= 0:
            raise serializers.ValidationError(f"{self._label} must be positive.")
        if quantity < 0:
            raise serializers.ValidationError(f"{self._label} must not be negative.")
        return quantity

    def to_representation(self, value):
        return _format_quantity(value)


# --- read representations -----------------------------------------------------


class ProductSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ("id", "name", "unit", "created_at")
        read_only_fields = fields


class LotSerializer(serializers.ModelSerializer):
    """Read representation of a stock lot (balance is ledger-derived)."""

    product = ProductSummarySerializer(read_only=True)
    purchase_quantity = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()
    expiry_group = serializers.SerializerMethodField()

    class Meta:
        model = StockLot
        fields = (
            "id",
            "product",
            "purchase_quantity",
            "balance",
            "unit",
            "location",
            "purchased_at",
            "expires_on",
            "expiry_group",
            "created_at",
        )
        read_only_fields = fields

    def get_purchase_quantity(self, lot):
        return _format_quantity(lot.quantity)

    def get_balance(self, lot):
        return _format_quantity(services.lot_balance(lot))

    def get_expiry_group(self, lot):
        today = timezone.localdate()
        expires_on = lot.expires_on
        if expires_on is None:
            return "later_or_no_date"
        if expires_on < today:
            return "expired"
        if expires_on == today:
            return "today"
        if expires_on <= today + timedelta(days=2):
            return "next_2_days"
        return "later_or_no_date"


class LotEventSerializer(serializers.ModelSerializer):
    """Read representation of one immutable ledger event.

    ``quantity`` is the absolute value; ``signed_quantity`` reflects ledger
    semantics: ADD is positive, CONSUME/DISCARD are negative, ADJUST signed.
    """

    quantity = serializers.SerializerMethodField()
    signed_quantity = serializers.SerializerMethodField()

    class Meta:
        model = InventoryEvent
        fields = ("id", "lot_id", "event_type", "quantity", "signed_quantity", "unit", "note", "created_at")
        read_only_fields = fields

    def get_quantity(self, event):
        return _format_quantity(abs(event.quantity))

    def get_signed_quantity(self, event):
        return _format_quantity(event.quantity)


# --- command inputs -----------------------------------------------------------


class AddLotCommandSerializer(serializers.Serializer):
    """POST /api/v1/inventory/lots/ body."""

    product_name = serializers.CharField(max_length=200)
    quantity = ExactDecimalField(label="quantity", required_positive=True)
    unit = serializers.ChoiceField(choices=Product.Unit.choices)
    location = serializers.ChoiceField(
        choices=StockLot.Location.choices, required=False, default=StockLot.Location.PANTRY
    )
    purchased_at = serializers.DateField(required=False, allow_null=True, default=None)
    expires_on = serializers.DateField(required=False, allow_null=True, default=None)
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")

    def validate(self, data):
        if not data["product_name"].strip():
            raise serializers.ValidationError({"product_name": "Product name must not be empty."})
        return data


class MutateLotCommandSerializer(serializers.Serializer):
    """POST /api/v1/inventory/lots/<uuid>/consume|discard/ body."""

    quantity = ExactDecimalField(label="quantity", required_positive=True)
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class CorrectLotCommandSerializer(serializers.Serializer):
    """POST /api/v1/inventory/lots/<uuid>/correct/ body."""

    observed_balance = ExactDecimalField(label="observed balance")
    reason = serializers.CharField(max_length=200, allow_blank=False)


# --- meal reads ---------------------------------------------------------------


def api_timestamp(value):
    """One deterministic API timestamp format: ISO-8601 UTC with a ``Z``
    suffix (DRF-style). Used by every API datetime so list, detail, and
    command responses render identically.

    Naive datetimes (e.g. read back from a SQLite test database with
    ``USE_TZ`` disabled) are treated as UTC; aware datetimes are converted.
    """
    if value.tzinfo is None:
        value = timezone.make_aware(value)
    text = value.astimezone(_dt_timezone.utc).isoformat()
    if text.endswith("+00:00"):
        text = text[:-6] + "Z"
    return text


def _cooked_at(suggestion):
    """ISO-8601 Z-suffix ``cooked_at`` from the household's MealEvent, else
    None — the same representation as every other API timestamp."""
    event = getattr(suggestion, "meal_event", None)
    if event is None:
        event = getattr(suggestion, "_prefetched", {}).get("meal_event")
    if event is None:
        return None
    return api_timestamp(event.cooked_at)


class _QuantityMixin:
    """Exact 3dp string rendering for Decimal quantity fields."""

    _quantity_fields = ()

    def get_fields(self):
        fields = super().get_fields()
        for name in self._quantity_fields:
            if name in fields:
                fields[name] = ExactDecimalField(read_only=True, required=False)
        return fields


class MealIngredientSerializer(_QuantityMixin, serializers.ModelSerializer):
    """Immutable ingredient snapshot with safe allocations only."""

    _quantity_fields = ("required_quantity", "owned_quantity", "missing_quantity")
    allocations = serializers.SerializerMethodField()

    class Meta:
        model = MealIngredient
        fields = (
            "id",
            "name",
            "unit",
            "required_quantity",
            "owned_quantity",
            "missing_quantity",
            "rescued",
            "allocations",
        )
        read_only_fields = fields

    @staticmethod
    def _allocation_lot_pk(entry):
        """Normalize a stored allocation lot id to a UUID, or None.

        Stored allocation lot ids are strings; queryset lookups key on
        UUIDs, so every id is normalized before the lookup. Unparseable
        ids yield None so the entry is omitted rather than guessed.
        """
        raw = entry.get("lot")
        if not raw:
            return None
        try:
            return uuid.UUID(str(raw))
        except (ValueError, TypeError):
            return None

    def get_allocations(self, ingredient):
        """Safe allocation entries: only household-owned lots, service-safe
        fields, quantities rendered as exact 3dp strings.

        Malformed entries (unparseable lot ids or quantities) are omitted
        entirely so every emitted quantity stays an exact 3dp string and
        no foreign or unknown lot is ever exposed.
        """
        household_pk = ingredient.household_id
        entries = [e for e in (ingredient.allocations or []) if isinstance(e, dict)]
        pks = []
        for entry in entries:
            pk = self._allocation_lot_pk(entry)
            if pk is not None:
                pks.append(pk)
        lots = {
            lot.pk: lot
            for lot in StockLot.objects.filter(pk__in=pks, household_id=household_pk)
        }
        out = []
        for entry in entries:
            lot = lots.get(self._allocation_lot_pk(entry))
            if lot is None:
                # Not this household's lot (or a malformed id): never
                # expose it.
                continue
            try:
                quantity = _format_quantity(entry.get("quantity"))
            except (InvalidOperation, ValueError, TypeError):
                # Malformed quantity: omit the entry entirely.
                continue
            out.append(
                {
                    "lot_id": str(lot.pk),
                    "quantity": quantity,
                    "unit": ingredient.unit,
                    "rescued": bool(entry.get("rescued", False)),
                    "expires_on": lot.expires_on.isoformat() if lot.expires_on else None,
                }
            )
        return out


class MealSuggestionSerializer(serializers.ModelSerializer):
    """Full immutable detail: proposal fields + ordered ingredients."""

    ingredients = MealIngredientSerializer(many=True, read_only=True)
    cooked_at = serializers.SerializerMethodField()

    class Meta:
        model = MealSuggestion
        fields = (
            "id",
            "status",
            "title",
            "servings",
            "time_minutes",
            "steps",
            "substitutions",
            "safety_note",
            "rationale",
            "provider_model",
            "created_at",
            "cooked_at",
            "ingredients",
        )
        read_only_fields = fields

    def get_cooked_at(self, suggestion):
        return _cooked_at(suggestion)


class MealSuggestionSummarySerializer(serializers.ModelSerializer):
    """List representation with derived missing/rescued counts."""

    cooked_at = serializers.SerializerMethodField()
    missing_ingredient_count = serializers.SerializerMethodField()
    rescued_ingredient_count = serializers.SerializerMethodField()

    class Meta:
        model = MealSuggestion
        fields = (
            "id",
            "title",
            "status",
            "servings",
            "time_minutes",
            "created_at",
            "cooked_at",
            "missing_ingredient_count",
            "rescued_ingredient_count",
        )
        read_only_fields = fields

    def get_cooked_at(self, suggestion):
        return _cooked_at(suggestion)

    def get_missing_ingredient_count(self, suggestion):
        return sum(1 for i in suggestion.ingredients.all() if i.missing_quantity > 0)

    def get_rescued_ingredient_count(self, suggestion):
        return sum(1 for i in suggestion.ingredients.all() if i.rescued)


# --- meal command inputs --------------------------------------------------------


class GenerateMealCommandSerializer(serializers.Serializer):
    """POST /api/v1/meals/generate/ body."""

    servings = serializers.IntegerField(
        min_value=1, max_value=_ai_schema.MAX_SERVINGS
    )
    max_minutes = serializers.IntegerField(
        min_value=_ai_schema.MIN_TIME_MINUTES,
        max_value=_ai_schema.MAX_TIME_MINUTES,
    )
    dietary_exclusions = serializers.ListField(
        child=serializers.CharField(max_length=200, allow_blank=False),
        required=False,
        default=list,
        max_length=20,
    )
    preference = serializers.CharField(max_length=200, required=False, default="")
    include_expired = serializers.BooleanField(required=False, default=False)

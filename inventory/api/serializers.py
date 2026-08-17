"""DRF serializers for the inventory API.

Quantities are exact three-decimal-place strings on the wire. Input accepts
JSON numbers only when they are finite and exact to 3 places (bools are
rejected); output is always an exact string rendered from the ``Decimal``.
No float arithmetic anywhere.
"""

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.utils import timezone
from rest_framework import serializers

from inventory import services
from inventory.models import InventoryEvent, Product, StockLot

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

    def __init__(self, label="quantity", required_positive=False, allow_zero=False, **kwargs):
        self._label = label
        self._required_positive = required_positive
        self._allow_zero = allow_zero
        kwargs.setdefault("required", True)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        try:
            quantity = _to_exact_decimal(data, self._label)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))
        if self._required_positive and quantity <= 0:
            raise serializers.ValidationError(f"{self._label} must be positive.")
        if not self._allow_zero and quantity < 0:
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

    observed_balance = ExactDecimalField(label="observed balance", allow_zero=True)
    reason = serializers.CharField(max_length=200, allow_blank=False)

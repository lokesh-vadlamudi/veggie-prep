"""HTML form definitions for the inventory web workflow.

Form fields provide input-level validation (types, choices, required).
All domain rules (positivity, exact 3-decimal quantities, unit
compatibility, household ownership) are re-enforced by
:mod:`inventory.services`, which is the single source of truth.
"""

from decimal import Decimal, InvalidOperation

from django import forms

from .models import Product, StockLot

_EXACT_QUANTITY_STEP = Decimal("0.001")


class ExactDecimalField(forms.DecimalField):
    """DecimalField that rejects values needing more than 3 decimal places.

    Django's :class:`forms.DecimalField` silently rounds to ``decimal_places``
    in ``to_python``; the inventory domain requires exact 3-dp quantities, so
    values like ``0.1234`` must be an error rather than a silent ``0.123``.
    """

    def clean(self, value):
        raw = value
        if raw not in self.empty_values:
            try:
                if isinstance(raw, Decimal):
                    number = raw
                else:
                    number = Decimal(str(raw).strip())
            except (InvalidOperation, ValueError):
                number = None
            if number is not None and number != number.quantize(_EXACT_QUANTITY_STEP):
                raise forms.ValidationError(
                    "Use at most 3 decimal places (exact quantity)."
                )
        return super().clean(value)


class AddStockForm(forms.Form):
    """Fast-add flow: record a new stock lot for the logged-in household."""

    product_name = forms.CharField(
        label="Product",
        max_length=200,
        strip=True,
        help_text="Existing products are reused when the name matches (case-insensitive).",
    )
    quantity = ExactDecimalField(
        label="Quantity",
        max_digits=12,
        decimal_places=3,
        min_value=Decimal("0.001"),
        help_text="Positive quantity, up to 3 decimal places.",
    )
    unit = forms.ChoiceField(label="Unit", choices=Product.Unit.choices)
    location = forms.ChoiceField(
        label="Location",
        choices=StockLot.Location.choices,
        initial=StockLot.Location.PANTRY,
    )
    purchased_at = forms.DateField(
        label="Purchased on", required=False, initial=None
    )
    expires_on = forms.DateField(
        label="Expires on", required=False, initial=None
    )
    note = forms.CharField(label="Note", required=False, max_length=200, strip=True)


class LotMutationForm(forms.Form):
    """Consume / discard: take a positive quantity out of a lot."""

    quantity = ExactDecimalField(
        label="Quantity",
        max_digits=12,
        decimal_places=3,
        min_value=Decimal("0.001"),
    )
    note = forms.CharField(label="Note", required=False, max_length=200, strip=True)


class CorrectionForm(forms.Form):
    """Correct: submit the observed balance; the signed delta is computed."""

    observed_balance = ExactDecimalField(
        label="Observed balance",
        max_digits=12,
        decimal_places=3,
        min_value=Decimal("0"),
        help_text="The balance you actually counted. The correction delta is applied automatically.",
    )
    reason = forms.CharField(
        label="Reason",
        required=True,
        max_length=200,
        strip=True,
        help_text="Required: why the recorded balance needed correcting.",
    )

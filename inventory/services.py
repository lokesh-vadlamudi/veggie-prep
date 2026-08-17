"""Transaction-safe application services for inventory mutations.

Balance model
-------------
The current quantity available in a lot is always *derived* from its
signed, immutable ledger events; no balance is stored or mutated in place:

    ADD       +quantity       (stock received; a new lot plus its event)
    CONSUME   -quantity       (stock used)
    DISCARD   -quantity       (stock thrown away)
    ADJUST    signed delta    (correction: positive increases, negative
                               decreases, zero is rejected)

``StockLot.quantity`` records the lot's purchase size only; it is
informational and is never used for balance calculations.

Conventions
-----------
* Quantities are exact decimals with at most 3 decimal places (matching
  the model fields). Pass a ``Decimal`` or an exact numeric string; floats
  and values needing rounding are rejected.
* Units must be one of the supported choices and must match the lot's (or
  product's, on add) unit exactly -- no implicit conversions (g vs kg,
  count vs each).
* Every mutating service runs in a single transaction. Consume, discard,
  and adjust additionally take a row lock (``select_for_update``) on the
  lot, so concurrent mutations of the same lot are serialized on backends
  that support locking reads. ``add_stock`` creates a fresh row and needs
  no lock.
* Service-created events are validated with ``full_clean`` before
  insertion. Any raised exception rolls the whole transaction back.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction

from .exceptions import (
    HouseholdMismatch,
    InsufficientStock,
    InvalidAdjustment,
    InvalidQuantity,
    InvalidUnit,
    UnitMismatch,
)
from .models import InventoryEvent, Product, StockLot

#: Quantities are stored with exactly this precision.
THREE_PLACES = Decimal("0.001")


def lot_balance(lot):
    """Current quantity available in ``lot``, derived from its events.

    The sum is computed in Python from one exact ``Decimal`` per event row
    instead of a database ``SUM`` aggregate so the result is exact on every
    backend: SQLite stores decimals as REAL/TEXT, and a float aggregate can
    introduce rounding error (e.g. 0.1 + 0.2 -> 0.30000000000000004).
    """
    total = Decimal("0")
    for quantity in InventoryEvent.objects.filter(
        lot_id=lot.pk
    ).values_list("quantity", flat=True):
        total += quantity
    return total


# --- validation helpers ------------------------------------------------------


def _as_exact_quantity(value, label):
    """Coerce ``value`` to a finite Decimal exact to 3 decimal places."""
    try:
        quantity = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise InvalidQuantity(
            f"{label} must be a number, got {value!r}."
        ) from None
    if not quantity.is_finite():
        raise InvalidQuantity(f"{label} must be a finite number.")
    if quantity != quantity.quantize(THREE_PLACES):
        raise InvalidQuantity(
            f"{label} may have at most 3 decimal places."
        )
    return quantity


def _require_positive(quantity, label="quantity"):
    if quantity <= 0:
        raise InvalidQuantity(f"{label} must be positive.")
    return quantity


def _require_known_unit(unit):
    if unit not in Product.Unit.values:
        raise InvalidUnit(f"Unknown unit {unit!r}.")
    return unit


def _require_known_location(location):
    if location not in StockLot.Location.values:
        raise InvalidUnit(f"Unknown location {location!r}.")
    return location


def _require_optional_date(value, label):
    if value is not None and not isinstance(value, date):
        raise ValueError(f"{label} must be a date.")


def _require_product_owned(household, product):
    if product.household_id != household.pk:
        raise HouseholdMismatch("Product does not belong to this household.")


def _lock_lot(household, lot):
    """Return ``lot`` under a row lock, only if it belongs to ``household``.

    Raises :class:`HouseholdMismatch` when the lot is absent from this
    household (whether it belongs to another household or does not exist).
    """
    locked = (
        StockLot.objects.select_for_update()
        .filter(pk=lot.pk, household_id=household.pk)
        .first()
    )
    if locked is None:
        raise HouseholdMismatch("Lot does not belong to this household.")
    return locked


def _require_unit_compatible(unit, lot):
    if unit != lot.unit:
        raise UnitMismatch(
            f"Unit {unit!r} is not compatible with the lot's unit "
            f"{lot.unit!r}."
        )


def _make_event(*, household, lot, event_type, quantity, unit, note=""):
    """Build, validate, and insert one ledger event. Returns the event."""
    event = InventoryEvent(
        household=household,
        lot=lot,
        event_type=event_type,
        quantity=quantity,
        unit=unit,
        note=note,
    )
    event.full_clean()  # validate before insertion
    event.save()
    return event


# --- services -----------------------------------------------------------------


@transaction.atomic
def add_stock(
    *,
    household,
    product,
    quantity,
    unit,
    location=StockLot.Location.PANTRY,
    purchased_at=None,
    expires_on=None,
    note="",
):
    """Receive a new stock lot for ``product``; record its ADD event.

    ``quantity`` must be positive and exact. ``unit`` must equal the
    product's unit. Returns the new :class:`StockLot`.
    """
    quantity = _require_positive(_as_exact_quantity(quantity, "quantity"))
    _require_known_unit(unit)
    _require_known_location(location)
    _require_optional_date(purchased_at, "purchased_at")
    _require_optional_date(expires_on, "expires_on")
    _require_product_owned(household, product)
    if unit != product.unit:
        raise UnitMismatch(
            f"Unit {unit!r} is not compatible with the product's unit "
            f"{product.unit!r}."
        )
    lot = StockLot(
        household=household,
        product=product,
        quantity=quantity,
        unit=unit,
        location=location,
        purchased_at=purchased_at,
        expires_on=expires_on,
    )
    lot.full_clean()
    lot.save()
    _make_event(
        household=household,
        lot=lot,
        event_type=InventoryEvent.EventType.ADD,
        quantity=quantity,
        unit=unit,
        note=note,
    )
    return lot


def _reduce_stock(*, household, lot, quantity, unit, event_type, verb, note=""):
    """Shared path for consume/discard: subtract a positive amount."""
    quantity = _require_positive(_as_exact_quantity(quantity, "quantity"))
    _require_known_unit(unit)
    locked = _lock_lot(household, lot)
    _require_unit_compatible(unit, locked)
    balance = lot_balance(locked)
    if quantity > balance:
        raise InsufficientStock(
            f"Cannot {verb} {quantity} {unit}; lot balance is "
            f"{balance} {locked.unit}."
        )
    return _make_event(
        household=household,
        lot=locked,
        event_type=event_type,
        quantity=-quantity,
        unit=unit,
        note=note,
    )


@transaction.atomic
def consume_stock(*, household, lot, quantity, unit, note=""):
    """Consume a positive, exact ``quantity`` from ``lot``.

    Returns the signed CONSUME event (negative quantity). Raises
    :class:`InsufficientStock` without writing anything when the lot's
    derived balance would become negative.
    """
    return _reduce_stock(
        household=household,
        lot=lot,
        quantity=quantity,
        unit=unit,
        event_type=InventoryEvent.EventType.CONSUME,
        verb="consume",
        note=note,
    )


@transaction.atomic
def discard_stock(*, household, lot, quantity, unit, note=""):
    """Discard a positive, exact ``quantity`` from ``lot``.

    Returns the signed DISCARD event (negative quantity).
    """
    return _reduce_stock(
        household=household,
        lot=lot,
        quantity=quantity,
        unit=unit,
        event_type=InventoryEvent.EventType.DISCARD,
        verb="discard",
        note=note,
    )


@transaction.atomic
def adjust_stock(*, household, lot, delta, unit, note=""):
    """Apply a signed correction ``delta`` to ``lot``'s balance.

    Direction is explicit: a positive delta increases the balance, a
    negative delta decreases it, and a zero delta is rejected. Returns the
    signed ADJUST event.
    """
    delta = _as_exact_quantity(delta, "delta")
    if delta == 0:
        raise InvalidAdjustment("Adjustment delta must be non-zero.")
    _require_known_unit(unit)
    locked = _lock_lot(household, lot)
    _require_unit_compatible(unit, locked)
    balance = lot_balance(locked)
    if balance + delta < 0:
        raise InsufficientStock(
            f"Adjustment {delta} would make the lot balance negative "
            f"({balance} {locked.unit} + {delta} {unit})."
        )
    return _make_event(
        household=household,
        lot=locked,
        event_type=InventoryEvent.EventType.ADJUST,
        quantity=delta,
        unit=unit,
        note=note,
    )

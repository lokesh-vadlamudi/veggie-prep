"""Validation and normalization of provider meal proposals.

The provider must return a single JSON *object*. :func:`validate_proposal`
turns that object into an immutable :class:`MealProposal` or raises
:class:`~inventory.ai.exceptions.AIMalformedOutputError` with a useful,
user-safe message. All limits are bounded so that oversized or
pathological output cannot reach the database.

Rules (violations raise ``AIMalformedOutputError``):

* ``title``: non-empty string, at most :data:`MAX_TITLE` chars.
* ``servings`` / ``time_minutes``: integers within bounded ranges
  (booleans are rejected even though ``bool`` subclasses ``int``).
* ``steps``: non-empty list of strings, each bounded in length.
* ``substitutions``: optional list of bounded strings.
* ``safety_note``: optional bounded string; ``rationale``: required
  non-empty string, bounded.
* ``ingredients``: non-empty list, each a dict with ``name``, ``unit``,
  ``quantity``; duplicate (name, unit) pairs are rejected.
* Names are normalized with
  :func:`inventory.services.normalize_product_name` and bounded in
  length.
* Units must match a :class:`inventory.models.Product.Unit` value
  exactly (``"g"``, never ``"G"`` or ``"grams"``); no conversions.
* Quantities must be positive, finite, exact to 3 decimal places, and at
  most :data:`MAX_QUANTITY`.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from ..models import Product
from ..services import normalize_product_name
from .exceptions import AIMalformedOutputError

MAX_TITLE = 200
MIN_SERVINGS = 1
MAX_SERVINGS = 50
MIN_TIME_MINUTES = 5
MAX_TIME_MINUTES = 600
MAX_STEPS = 50
MAX_STEP_LENGTH = 500
MAX_SUBSTITUTIONS = 20
MAX_SUBSTITUTION_LENGTH = 300
MAX_SAFETY_NOTE = 500
MAX_RATIONALE = 2000
MAX_INGREDIENTS = 30
MAX_NAME_LENGTH = 100
MAX_QUANTITY = Decimal("9999999999.999")

THREE_PLACES = Decimal("0.001")
_SUPPORTED_UNITS = set(Product.Unit.values)


def _fail(message: str) -> None:
    raise AIMalformedOutputError(f"AI output rejected: {message}")


def _text(value, field: str, *, required: bool, max_length: int) -> str:
    if value is None:
        if required:
            _fail(f"'{field}' is required.")
        return ""
    if not isinstance(value, str):
        _fail(f"'{field}' must be a string.")
    text = normalize_product_name(value)
    if required and not text:
        _fail(f"'{field}' must not be empty.")
    if len(text) > max_length:
        _fail(f"'{field}' is too long (max {max_length} characters).")
    return text


def _bounded_int(value, field: str, *, min_value: int, max_value: int) -> int:
    # bool is an int subclass; reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(f"'{field}' must be an integer.")
    if not (min_value <= value <= max_value):
        _fail(f"'{field}' must be between {min_value} and {max_value}.")
    return value


def _string_list(value, field: str, *, max_items: int, max_length: int,
                 required: bool) -> tuple[str, ...]:
    if value is None:
        if required:
            _fail(f"'{field}' is required and must be a non-empty list.")
        return ()
    if not isinstance(value, list):
        _fail(f"'{field}' must be a list of strings.")
    if len(value) > max_items:
        _fail(f"'{field}' has at most {max_items} items.")
    items = []
    for i, item in enumerate(value):
        if not isinstance(item, str):
            _fail(f"'{field}[{i}]' must be a string.")
        text = normalize_product_name(item)
        if not text:
            _fail(f"'{field}[{i}]' must not be empty.")
        if len(text) > max_length:
            _fail(
                f"'{field}[{i}]' is too long "
                f"(max {max_length} characters)."
            )
        items.append(text)
    if required and not items:
        _fail(f"'{field}' must contain at least one item.")
    return tuple(items)


def _exact_quantity(value, field: str) -> Decimal:
    """Parse ``value`` into a positive, finite, 3-dp-exact Decimal."""
    if isinstance(value, bool):
        _fail(f"'{field}' must be a positive number.")
    if isinstance(value, (int, float)):
        try:
            quantity = Decimal(value)
        except InvalidOperation:
            _fail(f"'{field}' must be a positive number.")
    elif isinstance(value, str):
        try:
            quantity = Decimal(value.strip())
        except InvalidOperation:
            _fail(f"'{field}' must be a positive number.")
    else:
        _fail(f"'{field}' must be a positive number.")
    if not quantity.is_finite():
        _fail(f"'{field}' must be a finite number.")
    if quantity <= 0:
        _fail(f"'{field}' must be positive.")
    if quantity > MAX_QUANTITY:
        _fail(f"'{field}' is too large (max {MAX_QUANTITY}).")
    if quantity % THREE_PLACES != 0:
        _fail(
            f"'{field}' must be exact to 3 decimal places "
            f"({value!r} is not)."
        )
    return quantity


@dataclass(frozen=True)
class IngredientProposal:
    name: str  # normalized
    unit: str  # exact Product.Unit value
    quantity: Decimal


@dataclass(frozen=True)
class MealProposal:
    """The validated, normalized provider proposal."""

    title: str
    servings: int
    time_minutes: int
    steps: tuple[str, ...]
    substitutions: tuple[str, ...]
    safety_note: str
    rationale: str
    ingredients: tuple[IngredientProposal, ...]
    provider_model: str = ""


def validate_proposal(payload: object, *, provider_model: str = "") -> MealProposal:
    """Validate ``payload`` (decoded JSON) into a :class:`MealProposal`.

    Raises :class:`AIMalformedOutputError` with a user-safe message on any
    violation. The returned object is fully normalized: trimmed strings,
    collapsed-whitespace ingredient names, exact ``Decimal`` quantities,
    exact unit strings.
    """
    if not isinstance(payload, dict):
        _fail("the proposal must be a JSON object.")

    title = _text(payload.get("title"), "title", required=True,
                  max_length=MAX_TITLE)
    servings = _bounded_int(payload.get("servings"), "servings",
                            min_value=MIN_SERVINGS, max_value=MAX_SERVINGS)
    time_minutes = _bounded_int(payload.get("time_minutes"), "time_minutes",
                                min_value=MIN_TIME_MINUTES,
                                max_value=MAX_TIME_MINUTES)
    steps = _string_list(payload.get("steps"), "steps", max_items=MAX_STEPS,
                         max_length=MAX_STEP_LENGTH, required=True)
    substitutions = _string_list(payload.get("substitutions"),
                                 "substitutions",
                                 max_items=MAX_SUBSTITUTIONS,
                                 max_length=MAX_SUBSTITUTION_LENGTH,
                                 required=False)
    safety_note = _text(payload.get("safety_note"), "safety_note",
                        required=False, max_length=MAX_SAFETY_NOTE)
    rationale = _text(payload.get("rationale"), "rationale", required=True,
                      max_length=MAX_RATIONALE)

    raw_ingredients = payload.get("ingredients")
    if not isinstance(raw_ingredients, list):
        _fail("'ingredients' is required and must be a list.")
    if not raw_ingredients:
        _fail("'ingredients' must contain at least one item.")
    if len(raw_ingredients) > MAX_INGREDIENTS:
        _fail(f"'ingredients' has at most {MAX_INGREDIENTS} items.")

    ingredients = []
    seen = set()
    for i, item in enumerate(raw_ingredients):
        if not isinstance(item, dict):
            _fail(f"'ingredients[{i}]' must be an object.")
        name = normalize_product_name(
            item.get("name") if isinstance(item.get("name"), str) else ""
        )
        if not name:
            _fail(f"'ingredients[{i}].name' must not be empty.")
        if len(name) > MAX_NAME_LENGTH:
            _fail(
                f"'ingredients[{i}].name' is too long "
                f"(max {MAX_NAME_LENGTH} characters)."
            )
        unit = item.get("unit")
        if not isinstance(unit, str) or unit not in _SUPPORTED_UNITS:
            _fail(
                f"'ingredients[{i}].unit' must be one of "
                f"{sorted(_SUPPORTED_UNITS)}."
            )
        quantity = _exact_quantity(item.get("quantity"),
                                   f"'ingredients[{i}].quantity'")
        key = (name.casefold(), unit)
        if key in seen:
            _fail(
                f"'ingredients[{i}]' duplicates {name!r} ({unit}); "
                "list each ingredient once."
            )
        seen.add(key)
        ingredients.append(IngredientProposal(name=name, unit=unit,
                                              quantity=quantity))

    return MealProposal(
        title=title,
        servings=servings,
        time_minutes=time_minutes,
        steps=steps,
        substitutions=substitutions,
        safety_note=safety_note,
        rationale=rationale,
        ingredients=tuple(ingredients),
        provider_model=provider_model,
    )

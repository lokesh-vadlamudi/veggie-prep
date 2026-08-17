"""Service-layer exceptions for inventory mutations.

All exceptions inherit from :class:`InventoryServiceError` so callers can
catch one base type around the service API. No exception here means
"validation failed, nothing was written" — every service rolls back its
transaction before the exception propagates.
"""


class InventoryServiceError(Exception):
    """Base class for inventory service-layer failures."""


class InvalidQuantity(InventoryServiceError):
    """A quantity is missing, not a number, not exact, or not positive."""


class InvalidUnit(InventoryServiceError):
    """A unit (or location) is not one of the supported choices."""


class UnitMismatch(InventoryServiceError):
    """A requested unit does not exactly match the lot's or product's unit."""


class HouseholdMismatch(InventoryServiceError):
    """An entity (product or lot) does not belong to the acting household."""


class InvalidAdjustment(InventoryServiceError):
    """An adjustment violates an adjustment-specific rule (e.g. zero delta)."""


class InsufficientStock(InventoryServiceError):
    """The mutation would drive the lot balance negative."""

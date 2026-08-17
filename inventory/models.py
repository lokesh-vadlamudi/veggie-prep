"""Inventory domain models.

All entities are scoped to a ``Household`` so that data is isolated between
households. ``InventoryEvent`` is append-only: existing events cannot be
updated or deleted through the model API. ``MealIngredient`` rows are
immutable reconciliation snapshots; ``MealSuggestion`` rows keep the
provider proposal immutable while the lifecycle ``status`` may move.
"""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class UUIDModel(models.Model):
    """Abstract base with a UUID primary key."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class Household(UUIDModel):
    """A household owns all inventory records.

    ``user`` ties the household to the Django user who created it. It is
    nullable so that households predating user linkage remain valid, and the
    ``post_save`` signal on the user model guarantees that every user ends up
    with exactly one household. ``on_delete=PROTECT`` ensures that deleting a
    user can never destroy an existing ledger.

    ``name`` is a display name only and is deliberately NOT unique: legacy or
    ownerless households may share names, and that must never block the
    automatic creation of a user's default household.
    """

    name = models.CharField(max_length=200)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="household",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class Product(UUIDModel):
    """A product known to one household."""

    class Unit(models.TextChoices):
        COUNT = "count", "count"
        EACH = "each", "each"
        GRAMS = "g", "grams"
        KILOGRAMS = "kg", "kilograms"
        MILLILITERS = "ml", "milliliters"
        LITERS = "l", "liters"

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="products"
    )
    name = models.CharField(max_length=200)
    unit = models.CharField(
        max_length=10, choices=Unit.choices, default=Unit.COUNT
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=["household", "name"], name="unique_product_name_per_household"
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.unit})"


class StockLot(UUIDModel):
    """A purchasable/consumable lot of a product within one household.

    ``quantity`` records the lot's purchase size. The currently available
    quantity is always derived from the lot's signed, immutable ledger events
    (see ``inventory.services.lot_balance``) and is never stored on the lot.
    """

    class Location(models.TextChoices):
        PANTRY = "pantry", "pantry"
        FRIDGE = "fridge", "fridge"
        FREEZER = "freezer", "freezer"

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="lots"
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="lots"
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit = models.CharField(
        max_length=10, choices=Product.Unit.choices, default=Product.Unit.COUNT
    )
    location = models.CharField(
        max_length=10, choices=Location.choices, default=Location.PANTRY
    )
    purchased_at = models.DateField(null=True, blank=True)
    expires_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self):
        return f"Lot {self.id} ({self.product})"

    def clean(self):
        super().clean()
        if self.pk or self.product_id:
            product = self.product
            if product.household_id != self.household_id:
                raise ValidationError(
                    {"product": "Lot's product must belong to the same household."}
                )


class InventoryEvent(UUIDModel):
    """An immutable ledger entry against a stock lot.

    Append-only: ``save`` refuses to update an existing event and ``delete``
    always raises. Balance is derived by summing events, never mutated in
    place.
    """

    class EventType(models.TextChoices):
        ADD = "ADD", "add"
        CONSUME = "CONSUME", "consume"
        DISCARD = "DISCARD", "discard"
        ADJUST = "ADJUST", "adjust"

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="events"
    )
    lot = models.ForeignKey(
        StockLot, on_delete=models.CASCADE, related_name="events"
    )
    event_type = models.CharField(
        max_length=10, choices=EventType.choices, default=EventType.ADD
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit = models.CharField(
        max_length=10, choices=Product.Unit.choices, default=Product.Unit.COUNT
    )
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")

    def __str__(self):
        return f"{self.event_type} {self.quantity} {self.unit} (lot {self.lot_id})"

    def clean(self):
        super().clean()
        if self.pk or self.lot_id:
            lot = self.lot
            if lot.household_id != self.household_id:
                raise ValidationError(
                    {"lot": "Event's lot must belong to the same household."}
                )

    def save(self, *args, **kwargs):
        # A freshly constructed instance has _state.adding=True; once the
        # first save succeeds Django flips it to False. Any subsequent save
        # (including update_fields) is therefore rejected.
        if not self._state.adding:
            raise ValueError(
                "InventoryEvent is append-only; existing events cannot be updated."
            )
        kwargs["force_insert"] = True
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(
            "InventoryEvent is append-only; events cannot be deleted."
        )


class MealSuggestion(UUIDModel):
    """An AI-proposed meal, scoped to one household.

    The stored provider proposal (title, servings, time, steps,
    substitutions, safety note, rationale, provider model) is immutable
    after the first save: it is a fixed record of what the provider
    proposed. Only the lifecycle ``status`` is expected to change later
    (cook confirmation flows build on it). No prompt/response text and no
    credentials are stored.
    """

    class Status(models.TextChoices):
        SUGGESTED = "suggested", "suggested"
        COOKED = "cooked", "cooked"
        REJECTED = "rejected", "rejected"

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="meal_suggestions"
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.SUGGESTED
    )
    title = models.CharField(max_length=200)
    servings = models.PositiveSmallIntegerField()
    time_minutes = models.PositiveSmallIntegerField()
    steps = models.JSONField(default=list)  # list[str], bounded by validator
    substitutions = models.JSONField(default=list)  # list[str]
    safety_note = models.CharField(max_length=500, blank=True, default="")
    rationale = models.TextField(blank=True, default="")  # "why this meal"
    provider_model = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    #: Fields that record the provider's proposal; immutable after save.
    _PROPOSAL_FIELDS = (
        "title",
        "servings",
        "time_minutes",
        "steps",
        "substitutions",
        "safety_note",
        "rationale",
        "provider_model",
    )

    @property
    def provider_snapshot(self):
        return (
            self.title,
            self.servings,
            self.time_minutes,
            tuple(self.steps or ()),
            tuple(self.substitutions or ()),
            self.safety_note,
            self.rationale,
            self.provider_model,
        )

    def save(self, *args, **kwargs):
        if self._state.adding or kwargs.get("raw") or kwargs.get("force_insert"):
            return super().save(*args, **kwargs)
        stored = type(self).objects.filter(pk=self.pk).first()
        if stored is not None and stored.provider_snapshot != self.provider_snapshot:
            raise ValueError(
                "The stored provider proposal is immutable; create a new "
                "suggestion instead of editing it."
            )
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"Suggestion {self.id}: {self.title}"


class MealIngredient(UUIDModel):
    """Immutable reconciliation snapshot of one proposed ingredient.

    ``required_quantity`` is what the meal needs; ``owned_quantity`` is
    what the household's matching lots (exact unit) cover;
    ``missing_quantity`` is the remainder to buy. ``rescued`` marks that at
    least one allocated lot was expiring (today/+1/+2, or explicitly
    included expired stock). ``allocations`` records which lots were drawn
    from, in deterministic order.
    """

    suggestion = models.ForeignKey(
        MealSuggestion, on_delete=models.CASCADE, related_name="ingredients"
    )
    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="meal_ingredients"
    )
    name = models.CharField(max_length=100)
    unit = models.CharField(max_length=10, choices=Product.Unit.choices)
    required_quantity = models.DecimalField(max_digits=12, decimal_places=3)
    owned_quantity = models.DecimalField(max_digits=12, decimal_places=3)
    missing_quantity = models.DecimalField(max_digits=12, decimal_places=3)
    rescued = models.BooleanField(default=False)
    allocations = models.JSONField(default=list)  # [{lot, quantity, rescued}]
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("suggestion", "name")
        constraints = [
            models.UniqueConstraint(
                fields=["suggestion", "name", "unit"],
                name="unique_ingredient_per_suggestion",
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError(
                "MealIngredient is an immutable reconciliation snapshot; "
                "it cannot be updated."
            )
        kwargs["force_insert"] = True
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(
            "MealIngredient is an immutable reconciliation snapshot; "
            "it cannot be deleted."
        )

    def __str__(self):
        return f"{self.name} ({self.required_quantity} {self.unit})"


class MealEvent(UUIDModel):
    """An immutable record that a suggested meal was cooked.

    Household-scoped, exactly one per suggestion (``OneToOne`` to
    ``MealSuggestion``): cook confirmation creates a single event that
    freezes the outcome and when it happened. Append-only like
    ``InventoryEvent``: ``save`` refuses to update an existing event and
    ``delete`` always raises.
    """

    class Outcome(models.TextChoices):
        SUCCESS = "success", "success"
        FAILED = "failed", "failed"

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="meal_events"
    )
    suggestion = models.OneToOneField(
        MealSuggestion, on_delete=models.CASCADE, related_name="meal_event"
    )
    outcome = models.CharField(
        max_length=10, choices=Outcome.choices, default=Outcome.SUCCESS
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"MealEvent {self.id} ({self.outcome}, suggestion {self.suggestion_id})"

    def clean(self):
        super().clean()
        if self.pk or self.suggestion_id:
            suggestion = self.suggestion
            if suggestion.household_id != self.household_id:
                raise ValidationError(
                    {"suggestion": "Event's suggestion must belong to the same household."}
                )

    def save(self, *args, **kwargs):
        # A freshly constructed instance has _state.adding=True; once the
        # first save succeeds Django flips it to False. Any subsequent save
        # (including update_fields) is therefore rejected.
        if not self._state.adding:
            raise ValueError(
                "MealEvent is append-only; existing events cannot be updated."
            )
        kwargs["force_insert"] = True
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("MealEvent is append-only; events cannot be deleted.")

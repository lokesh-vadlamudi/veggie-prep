from django.contrib import admin

from .models import (
    Household,
    InventoryEvent,
    MealEvent,
    MealIngredient,
    MealSuggestion,
    Product,
    StockLot,
)


class ProductInline(admin.TabularInline):
    model = Product
    extra = 0
    readonly_fields = ("id", "created_at")


class StockLotInline(admin.TabularInline):
    model = StockLot
    extra = 0
    readonly_fields = ("id", "created_at")


@admin.register(Household)
class HouseholdAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "user", "created_at")
    list_filter = ("user",)
    search_fields = ("name", "user__username")
    inlines = (ProductInline, StockLotInline)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "unit", "household", "created_at")
    list_filter = ("unit", "household")
    search_fields = ("name",)
    readonly_fields = ("id", "created_at")


@admin.register(StockLot)
class StockLotAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "product",
        "household",
        "quantity",
        "unit",
        "location",
        "purchased_at",
        "expires_on",
    )
    list_filter = ("unit", "location", "household", "product")
    readonly_fields = ("id", "created_at")


@admin.register(InventoryEvent)
class InventoryEventAdmin(admin.ModelAdmin):
    """Read-only: events are append-only and never edited or removed."""

    list_display = (
        "id",
        "event_type",
        "quantity",
        "unit",
        "lot",
        "household",
        "created_at",
    )
    list_filter = ("event_type", "unit", "household")
    search_fields = ("note",)
    readonly_fields = (
        "id",
        "household",
        "lot",
        "event_type",
        "quantity",
        "unit",
        "note",
        "created_at",
    )
    actions = None

    def has_add_permission(self, request):
        # Events are created by the domain layer, not by the admin.
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class MealEventInline(admin.TabularInline):
    """Read-only: cook events are created by the confirm service and are
    append-only."""

    model = MealEvent
    extra = 0
    readonly_fields = (
        "id",
        "household",
        "suggestion",
        "outcome",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class MealIngredientInline(admin.TabularInline):
    """Read-only: reconciliation snapshots are created by the generation
    service and never edited in the admin."""

    model = MealIngredient
    extra = 0
    readonly_fields = (
        "id",
        "name",
        "unit",
        "required_quantity",
        "owned_quantity",
        "missing_quantity",
        "rescued",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MealSuggestion)
class MealSuggestionAdmin(admin.ModelAdmin):
    """The provider proposal is read-only; only the lifecycle status moves."""

    list_display = (
        "id",
        "title",
        "household",
        "status",
        "servings",
        "time_minutes",
        "created_at",
    )
    list_filter = ("status", "household")
    search_fields = ("title", "rationale")
    readonly_fields = (
        "id",
        "household",
        "title",
        "servings",
        "time_minutes",
        "steps",
        "substitutions",
        "safety_note",
        "rationale",
        "provider_model",
        "created_at",
    )
    inlines = (MealEventInline, MealIngredientInline)
    actions = None

    def has_add_permission(self, request):
        # Suggestions are created by the generation service, not the admin.
        return False


@admin.register(MealIngredient)
class MealIngredientAdmin(admin.ModelAdmin):
    """Read-only: immutable reconciliation snapshots."""

    list_display = (
        "id",
        "suggestion",
        "name",
        "unit",
        "required_quantity",
        "owned_quantity",
        "missing_quantity",
        "rescued",
        "household",
    )
    list_filter = ("rescued", "unit", "household")
    search_fields = ("name",)
    readonly_fields = (
        "id",
        "suggestion",
        "household",
        "name",
        "unit",
        "required_quantity",
        "owned_quantity",
        "missing_quantity",
        "rescued",
        "allocations",
        "created_at",
    )
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MealEvent)
class MealEventAdmin(admin.ModelAdmin):
    """Read-only: events are append-only and never edited or removed."""

    list_display = (
        "id",
        "suggestion",
        "outcome",
        "household",
        "created_at",
    )
    list_filter = ("outcome", "household")
    search_fields = ("suggestion__title",)
    readonly_fields = (
        "id",
        "household",
        "suggestion",
        "outcome",
        "created_at",
    )
    actions = None

    def has_add_permission(self, request):
        # Events are created by the confirm-cook service, not by the admin.
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

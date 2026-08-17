from django.contrib import admin

from .models import Household, InventoryEvent, Product, StockLot


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

from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "inventory"

    def ready(self):
        # Connects the post_save signal that gives every user exactly one
        # default household (see inventory.signals).
        from . import signals  # noqa: F401

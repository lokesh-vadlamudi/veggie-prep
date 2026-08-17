from django.apps import AppConfig
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save


class InventoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "inventory"

    def ready(self):
        # Give every user exactly one default household (see
        # inventory.signals). Connected to settings.AUTH_USER_MODEL via
        # get_user_model() -- no coupling to the concrete auth model -- and
        # with a stable dispatch_uid so re-calling ready() is idempotent.
        from .signals import DISPATCH_UID, ensure_user_household

        post_save.connect(
            ensure_user_household,
            sender=get_user_model(),
            dispatch_uid=DISPATCH_UID,
        )

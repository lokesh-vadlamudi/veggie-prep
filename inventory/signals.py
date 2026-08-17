"""Signal handler that keeps household ownership consistent with users.

Every newly created user automatically receives exactly one default
household. The handler is idempotent (``get_or_create`` on the OneToOne
``user`` field), so repeated saves, duplicate signal deliveries, or a
manually pre-created household never produce a second household for the
same user.

The handler is model-agnostic: it works with whatever
``settings.AUTH_USER_MODEL`` is configured. Connection happens in
``inventory.apps.InventoryConfig.ready`` with a stable ``dispatch_uid`` so
that repeated calls to ``ready()`` never double-connect.
"""

from .models import Household

#: Stable connection id; makes repeated connects idempotent.
DISPATCH_UID = "inventory.ensure_user_household"


def default_household_name(user):
    """Deterministic default name for a user's auto-created household."""
    return f"{user.username}'s household"


def ensure_user_household(sender, instance=None, created=False, **kwargs):
    """Create the user's default household if it does not exist yet."""
    if instance is None or instance.pk is None:
        return
    Household.objects.get_or_create(
        user=instance,
        defaults={"name": default_household_name(instance)},
    )

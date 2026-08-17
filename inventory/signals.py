"""Signals that keep household ownership consistent with Django users.

Every newly created user automatically receives exactly one default
household. The handler is idempotent (``get_or_create``), so repeated saves,
duplicate signal deliveries, or a manually pre-created household never
produce a second household for the same user.
"""

from django.contrib.auth.models import User
from django.db.models.signals import post_save

from .models import Household


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


post_save.connect(ensure_user_household, sender=User)

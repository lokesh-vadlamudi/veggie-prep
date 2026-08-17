"""Signal tests: every user gets exactly one default household.

Covers automatic creation on user creation, idempotency under repeated
saves, duplicate signal fires, and duplicate ``ready()`` connections,
preservation of a manually created household, backfilling of legacy users,
the legacy default-name-collision defect, and user-deletion protection.
"""

import importlib
from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.db.models.deletion import ProtectedError
from django.db.models.signals import post_save
from django.test import TestCase

from inventory.models import Household
from inventory.signals import DISPATCH_UID, ensure_user_household


def _create_user_no_signal(username):
    """Create a user with the household signal temporarily disconnected,
    simulating a user that predates user/household linkage."""
    post_save.disconnect(
        ensure_user_household,
        sender=User,
        dispatch_uid=DISPATCH_UID,
    )
    try:
        return User.objects.create(username=username)
    finally:
        post_save.connect(
            ensure_user_household,
            sender=User,
            dispatch_uid=DISPATCH_UID,
        )


def _backfill_operation():
    """The exact RunPython function of migration 0002, for direct reuse."""
    module = importlib.import_module(
        "inventory.migrations.0002_backfill_user_households"
    )
    from django.apps import apps

    return module.backfill_households(apps, None)


class UserHouseholdSignalTests(TestCase):
    def test_user_creation_creates_default_household(self):
        user = User.objects.create_user(username="chef", password="x")
        household = Household.objects.get(user=user)
        # Related name resolves both directions.
        self.assertEqual(user.household, household)
        self.assertEqual(household.name, "chef's household")

    def test_repeated_saves_create_only_one_household(self):
        user = User.objects.create_user(username="chef1", password="x")
        for _ in range(3):
            user.save()
        self.assertEqual(Household.objects.filter(user=user).count(), 1)

    def test_double_signal_fire_is_idempotent(self):
        user = User.objects.create_user(username="chef2", password="x")
        ensure_user_household(sender=User, instance=user, created=True)
        ensure_user_household(sender=User, instance=user, created=True)
        self.assertEqual(Household.objects.filter(user=user).count(), 1)

    def test_duplicate_ready_connection_is_idempotent(self):
        """Reconnecting with the same dispatch_uid must not double-fire."""
        post_save.connect(
            ensure_user_household,
            sender=get_user_model(),
            dispatch_uid=DISPATCH_UID,
        )
        post_save.connect(
            ensure_user_household,
            sender=get_user_model(),
            dispatch_uid=DISPATCH_UID,
        )
        user = User.objects.create_user(username="chef9", password="x")
        self.assertEqual(Household.objects.filter(user=user).count(), 1)

    def test_manually_created_household_is_not_duplicated(self):
        user = _create_user_no_signal("chef3")
        Household.objects.create(name="Custom name", user=user)
        user.save()
        self.assertEqual(Household.objects.filter(user=user).count(), 1)
        self.assertEqual(Household.objects.get(user=user).name, "Custom name")

    def test_legacy_user_without_household_gets_one_on_next_save(self):
        user = _create_user_no_signal("chef4")
        self.assertEqual(Household.objects.filter(user=user).count(), 0)
        user.save()
        self.assertEqual(Household.objects.filter(user=user).count(), 1)
        self.assertEqual(
            Household.objects.get(user=user).name, "chef4's household"
        )

    def test_users_get_distinct_households(self):
        a = User.objects.create_user(username="alpha", password="x")
        b = User.objects.create_user(username="beta", password="x")
        self.assertNotEqual(a.household.id, b.household.id)

    def test_user_delete_is_protected_while_household_exists(self):
        user = User.objects.create_user(username="chef5", password="x")
        with self.assertRaises(ProtectedError):
            user.delete()
        self.assertTrue(User.objects.filter(pk=user.pk).exists())


class DefaultNameCollisionRegressionTests(TestCase):
    """Regression: a legacy ownerless household that already uses the
    default name must not block user creation or the 0002 backfill."""

    def test_ownerless_collision_does_not_block_user_creation(self):
        # Legacy ownerless household with the exact default name.
        Household.objects.create(name="chef6's household")
        user = User.objects.create_user(username="chef6", password="x")
        # User creation succeeds and the user gets its own household.
        self.assertEqual(Household.objects.filter(user=user).count(), 1)
        self.assertEqual(Household.objects.count(), 2)

    def test_different_households_may_share_a_display_name(self):
        a = Household.objects.create(name="Shared name")
        b = Household.objects.create(name="Shared name")
        self.assertNotEqual(a.id, b.id)

    def test_backfill_does_not_block_on_collision(self):
        """Run the actual 0002 backfill over legacy colliding state."""
        Household.objects.create(name="chef7's household")
        user = _create_user_no_signal("chef7")
        self.assertEqual(Household.objects.filter(user=user).count(), 0)
        _backfill_operation()
        self.assertEqual(Household.objects.filter(user=user).count(), 1)
        self.assertEqual(
            Household.objects.get(user=user).name, "chef7's household"
        )
        # The legacy ownerless household is untouched.
        self.assertEqual(Household.objects.count(), 2)

    def test_backfill_is_idempotent(self):
        user = User.objects.create_user(username="chef8", password="x")
        _backfill_operation()
        _backfill_operation()
        self.assertEqual(Household.objects.filter(user=user).count(), 1)

    def test_exactly_one_household_per_user_still_enforced(self):
        """OneToOne uniqueness: a second household for the same user fails
        even though display names are no longer unique."""
        from django.db import IntegrityError, transaction

        user = User.objects.create_user(username="solo2", password="x")
        household = Household.objects.get(user=user)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Household.objects.create(name=household.name, user=user)

"""Signal tests: every user gets exactly one default household.

Covers automatic creation on user creation, idempotency under repeated
saves and duplicate signal fires, preservation of a manually created
household, backfilling of legacy users, and user-deletion protection.
"""

from django.contrib.auth.models import User
from django.db.models.deletion import ProtectedError
from django.db.models.signals import post_save
from django.test import TestCase

from inventory.models import Household
from inventory.signals import ensure_user_household


def _create_user_no_signal(username):
    """Create a user with the household signal temporarily disconnected,
    simulating a user that predates user/household linkage."""
    post_save.disconnect(ensure_user_household, sender=User)
    try:
        return User.objects.create(username=username)
    finally:
        post_save.connect(ensure_user_household, sender=User)


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

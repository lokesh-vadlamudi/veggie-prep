"""Model tests for the inventory app.

Cover: creation, UUID primary keys, quantity precision, optional lot
dates, household isolation constraints, and append-only enforcement of
InventoryEvent via model methods.
"""

import uuid
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from inventory.models import (
    Household,
    InventoryEvent,
    MealEvent,
    MealSuggestion,
    Product,
    StockLot,
)


def make_household(name="House 1"):
    return Household.objects.create(name=name)


class HouseholdCreationTests(TestCase):
    def test_create_household_with_uuid_pk(self):
        household = make_household()
        self.assertEqual(type(household.pk), uuid.UUID)
        self.assertEqual(household.name, "House 1")
        self.assertIsNotNone(household.created_at)

    def test_household_names_are_not_unique(self):
        """Display names may repeat: legacy/ownerless households must be
        able to share a name without blocking new household creation."""
        first = make_household("House 1")
        second = make_household("House 1")
        self.assertNotEqual(first.id, second.id)


class ProductCreationTests(TestCase):
    def test_create_product_in_household(self):
        household = make_household()
        product = Product.objects.create(
            household=household, name="Egg", unit="each"
        )
        self.assertEqual(type(product.pk), uuid.UUID)
        self.assertEqual(product.unit, "each")
        self.assertEqual(household.products.get(), product)

    def test_unit_choices_rejected_by_validation(self):
        household = make_household()
        product = Product(household=household, name="Egg", unit="stone")
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_duplicate_name_allowed_across_households(self):
        """Household isolation: the same product name exists per household."""
        a = make_household("House A")
        b = make_household("House B")
        p1 = Product.objects.create(household=a, name="Egg", unit="each")
        p2 = Product.objects.create(household=b, name="Egg", unit="each")
        self.assertNotEqual(p1.id, p2.id)

    def test_duplicate_name_rejected_within_household(self):
        household = make_household()
        Product.objects.create(household=household, name="Egg", unit="each")
        duplicate = Product(
            household=household, name="Egg", unit="each"
        )
        with self.assertRaises(ValidationError):
            duplicate.full_clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                duplicate.save()


class StockLotTests(TestCase):
    def _lot(self, **overrides):
        defaults = dict(
            household=make_household(),
            product=None,
            quantity=Decimal("2.500"),
            unit="g",
        )
        defaults.update(overrides)
        if defaults["product"] is None:
            defaults["product"] = Product.objects.create(
                household=defaults["household"], name="Flour", unit="g"
            )
        return StockLot.objects.create(**defaults)

    def test_create_lot_with_quantity_and_unit(self):
        lot = self._lot(quantity=Decimal("2.5"))
        self.assertEqual(type(lot.pk), uuid.UUID)
        self.assertEqual(lot.quantity, Decimal("2.500"))
        self.assertEqual(lot.unit, "g")

    def test_quantity_precision_preserved_to_three_decimals(self):
        lot = self._lot(quantity=Decimal("0.123"))
        self.assertEqual(str(lot.quantity), "0.123")
        # A value beyond 3 decimal places cannot pass model validation.
        too_fine = StockLot(
            household=lot.household,
            product=lot.product,
            quantity=Decimal("0.1234"),
            unit="g",
        )
        with self.assertRaises(ValidationError):
            too_fine.full_clean()

    def test_quantity_is_stored_exactly(self):
        household = make_household("Precision")
        product = Product.objects.create(
            household=household, name="Salt", unit="g"
        )
        lot = StockLot.objects.create(
            household=household,
            product=product,
            quantity=Decimal("1.005"),
            unit="g",
        )
        reloaded = StockLot.objects.get(pk=lot.pk)
        self.assertEqual(reloaded.quantity, Decimal("1.005"))
        self.assertEqual(str(reloaded.quantity), "1.005")

    def test_optional_dates_default_to_none(self):
        lot = self._lot()
        self.assertIsNone(lot.purchased_at)
        self.assertIsNone(lot.expires_on)

    def test_optional_dates_can_be_set(self):
        lot = self._lot(
            purchased_at=date(2026, 8, 1), expires_on=date(2026, 9, 1)
        )
        self.assertEqual(lot.purchased_at, date(2026, 8, 1))
        self.assertEqual(lot.expires_on, date(2026, 9, 1))

    def test_lot_must_share_product_household(self):
        """Household isolation: a lot cannot use another household's product."""
        foreign = Product.objects.create(
            household=make_household("Other"), name="Flour", unit="g"
        )
        lot = StockLot(
            household=make_household("Own"),
            product=foreign,
            quantity=Decimal("1"),
            unit="g",
        )
        with self.assertRaises(ValidationError):
            lot.full_clean()

    def test_matching_households_pass_clean(self):
        lot = self._lot()
        lot.full_clean(exclude=["id"])  # no ValidationError


class StockLotLocationTests(TestCase):
    def _household_and_product(self):
        household = make_household()
        product = Product.objects.create(
            household=household, name="Milk", unit="l"
        )
        return household, product

    def test_location_defaults_to_pantry(self):
        household, product = self._household_and_product()
        lot = StockLot.objects.create(
            household=household,
            product=product,
            quantity=Decimal("1"),
            unit="l",
        )
        self.assertEqual(lot.location, "pantry")

    def test_explicit_locations_can_be_stored(self):
        household, product = self._household_and_product()
        for location in ("fridge", "freezer"):
            lot = StockLot.objects.create(
                household=household,
                product=product,
                quantity=Decimal("1"),
                unit="l",
                location=location,
            )
            self.assertEqual(lot.location, location)

    def test_invalid_location_rejected_by_validation(self):
        household, product = self._household_and_product()
        lot = StockLot(
            household=household,
            product=product,
            quantity=Decimal("1"),
            unit="l",
            location="basement",
        )
        with self.assertRaises(ValidationError):
            lot.full_clean()


class HouseholdUserTests(TestCase):
    def test_household_without_user_remains_valid(self):
        """Migration safety: households that predate user linkage persist."""
        household = make_household("Legacy")
        self.assertIsNone(household.user)

    def test_only_one_household_per_user(self):
        user = User.objects.create_user(username="solo", password="x")
        household = Household.objects.get(user=user)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Household.objects.create(name="Second", user=household.user)

    def test_user_reverse_accessor(self):
        user = User.objects.create_user(username="rev", password="x")
        self.assertEqual(user.household.name, "rev's household")


class InventoryEventTests(TestCase):
    def _event(self, event_type=InventoryEvent.EventType.ADD):
        household = Household.objects.create(name=f"Events {uuid.uuid4().hex[:8]}")
        product = Product.objects.create(
            household=household, name="Milk", unit="l"
        )
        lot = StockLot.objects.create(
            household=household,
            product=product,
            quantity=Decimal("1.000"),
            unit="l",
        )
        return InventoryEvent.objects.create(
            household=household,
            lot=lot,
            event_type=event_type,
            quantity=Decimal("1.000"),
            unit="l",
        )

    def test_create_event(self):
        event = self._event()
        self.assertEqual(type(event.pk), uuid.UUID)
        self.assertEqual(event.event_type, "ADD")
        self.assertEqual(event.quantity, Decimal("1.000"))

    def test_all_event_types_supported(self):
        for et in InventoryEvent.EventType.values:
            self._event(event_type=et)

    def test_event_quantity_precision(self):
        event = self._event()
        self.assertEqual(str(event.quantity), "1.000")

    def test_event_must_share_lot_household(self):
        """Household isolation: an event cannot reference a foreign lot."""
        household = make_household("Events")
        product = Product.objects.create(
            household=household, name="Milk", unit="l"
        )
        lot = StockLot.objects.create(
            household=household,
            product=product,
            quantity=Decimal("1.000"),
            unit="l",
        )
        event = InventoryEvent(
            household=make_household("Other"),
            lot=lot,
            event_type="ADD",
            quantity=Decimal("1.000"),
            unit="l",
        )
        with self.assertRaises(ValidationError):
            event.full_clean()

    def test_cannot_update_existing_event(self):
        event = self._event()
        event.quantity = Decimal("9.999")
        event.event_type = InventoryEvent.EventType.ADJUST
        with self.assertRaises(ValueError):
            event.save()
        # Update via update_fields is blocked the same way.
        with self.assertRaises(ValueError):
            event.save(update_fields=["quantity"])
        # The database row is untouched.
        reloaded = InventoryEvent.objects.get(pk=event.pk)
        self.assertEqual(reloaded.quantity, Decimal("1.000"))
        self.assertEqual(reloaded.event_type, "ADD")

    def test_cannot_delete_existing_event(self):
        event = self._event()
        with self.assertRaises(ValueError):
            event.delete()
        self.assertTrue(InventoryEvent.objects.filter(pk=event.pk).exists())

    def test_second_save_of_same_instance_raises(self):
        event = self._event()
        with self.assertRaises(ValueError):
            event.save()


def make_suggestion(household, title="Stir-fried greens"):
    return MealSuggestion.objects.create(
        household=household, title=title, servings=2, time_minutes=20
    )


class MealEventTests(TestCase):
    def _event(self, household, suggestion):
        return MealEvent.objects.create(household=household, suggestion=suggestion)

    def test_create_event_with_uuid_pk_and_cooked_at(self):
        household = make_household()
        suggestion = make_suggestion(household)
        event = self._event(household, suggestion)
        self.assertEqual(type(event.pk), uuid.UUID)
        self.assertIsNotNone(event.cooked_at)
        self.assertEqual(household.meal_events.get(), event)

    def test_no_persisted_outcome_or_failure_state(self):
        """Failures roll back with no record: the model exposes only
        ``cooked_at`` and persists no outcome/failure field."""
        field_names = [f.name for f in MealEvent._meta.get_fields()]
        self.assertNotIn("outcome", field_names)
        self.assertNotIn("created_at", field_names)
        self.assertIn("cooked_at", field_names)

    def test_exactly_one_event_per_suggestion(self):
        household = make_household()
        suggestion = make_suggestion(household)
        event = self._event(household, suggestion)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._event(household, suggestion)
        # Reverse accessor sees the single event.
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.meal_event.pk, event.pk)

    def test_event_must_share_suggestion_household(self):
        a = make_household("House A")
        b = make_household("House B")
        suggestion = make_suggestion(a)
        event = MealEvent(household=b, suggestion=suggestion)
        with self.assertRaises(ValidationError) as ctx:
            event.full_clean()
        self.assertIn("suggestion", ctx.exception.message_dict)

    def test_matching_households_pass_clean(self):
        household = make_household()
        suggestion = make_suggestion(household)
        event = MealEvent(household=household, suggestion=suggestion)
        event.full_clean()

    def test_cannot_update_existing_event(self):
        household = make_household()
        event = self._event(household, make_suggestion(household))
        event.household = make_household("House 2")
        with self.assertRaises(ValueError):
            event.save()
        with self.assertRaises(ValueError):
            event.save(update_fields=["household"])
        reloaded = MealEvent.objects.get(pk=event.pk)
        self.assertEqual(reloaded.household, household)

    def test_cannot_delete_existing_event(self):
        household = make_household()
        event = self._event(household, make_suggestion(household))
        with self.assertRaises(ValueError):
            event.delete()
        self.assertTrue(MealEvent.objects.filter(pk=event.pk).exists())

    def test_second_save_of_same_instance_raises(self):
        household = make_household()
        event = self._event(household, make_suggestion(household))
        with self.assertRaises(ValueError):
            event.save()

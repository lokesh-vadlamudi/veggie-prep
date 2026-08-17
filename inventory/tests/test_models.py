"""Model tests for the inventory app.

Cover: creation, UUID primary keys, quantity precision, optional lot
dates, household isolation constraints, and append-only enforcement of
InventoryEvent via model methods.
"""

import uuid
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from inventory.models import Household, InventoryEvent, Product, StockLot


def make_household(name="House 1"):
    return Household.objects.create(name=name)


class HouseholdCreationTests(TestCase):
    def test_create_household_with_uuid_pk(self):
        household = make_household()
        self.assertEqual(type(household.pk), uuid.UUID)
        self.assertEqual(household.name, "House 1")
        self.assertIsNotNone(household.created_at)

    def test_household_names_are_unique(self):
        make_household("House 1")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_household("House 1")


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

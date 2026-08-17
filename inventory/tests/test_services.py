"""Service tests for add_stock / consume_stock / discard_stock / adjust_stock.

Covers positive and exact-decimal inputs, signed-event semantics, household
isolation, exact unit compatibility, no-negative-balance enforcement,
transaction rollback on failure, row-lock usage on backends that support
locking reads, and preservation of lot attributes (location, dates).
"""

import uuid
from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from inventory import services
from inventory.exceptions import (
    HouseholdMismatch,
    InsufficientStock,
    InvalidAdjustment,
    InvalidQuantity,
    InvalidUnit,
    UnitMismatch,
)
from inventory.models import Household, InventoryEvent, Product, StockLot


def make_household_for_user():
    """Create a user; the post_save signal gives them their household."""
    user = User.objects.create_user(
        username=f"user-{uuid.uuid4().hex[:8]}", password="x"
    )
    return user, Household.objects.get(user=user)


def make_product(household, name="Flour", unit="g"):
    return Product.objects.create(household=household, name=name, unit=unit)


class AddStockServiceTests(TestCase):
    def setUp(self):
        self.user, self.household = make_household_for_user()
        self.product = make_product(self.household)

    def test_add_stock_creates_lot_and_positive_add_event(self):
        lot = services.add_stock(
            household=self.household,
            product=self.product,
            quantity=Decimal("2.500"),
            unit="g",
        )
        self.assertEqual(lot.quantity, Decimal("2.500"))
        self.assertEqual(lot.unit, "g")
        self.assertEqual(lot.household, self.household)
        self.assertEqual(lot.product, self.product)
        events = list(lot.events.all())
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "ADD")
        self.assertEqual(events[0].quantity, Decimal("2.500"))
        self.assertEqual(events[0].unit, "g")
        self.assertEqual(events[0].household, self.household)
        self.assertEqual(services.lot_balance(lot), Decimal("2.500"))

    def test_add_stock_default_location_is_pantry(self):
        lot = services.add_stock(
            household=self.household,
            product=self.product,
            quantity=Decimal("1"),
            unit="g",
        )
        self.assertEqual(lot.location, "pantry")

    def test_add_stock_stores_explicit_location(self):
        for location in ("fridge", "freezer"):
            lot = services.add_stock(
                household=self.household,
                product=self.product,
                quantity=Decimal("1"),
                unit="g",
                location=location,
            )
            self.assertEqual(lot.location, location)

    def test_add_stock_preserves_purchase_and_expiry_dates(self):
        lot = services.add_stock(
            household=self.household,
            product=self.product,
            quantity=Decimal("1"),
            unit="g",
            purchased_at=date(2026, 8, 1),
            expires_on=date(2026, 9, 1),
        )
        self.assertEqual(lot.purchased_at, date(2026, 8, 1))
        self.assertEqual(lot.expires_on, date(2026, 9, 1))

    def test_add_stock_rejects_zero_quantity(self):
        with self.assertRaises(InvalidQuantity):
            services.add_stock(
                household=self.household,
                product=self.product,
                quantity=Decimal("0"),
                unit="g",
            )

    def test_add_stock_rejects_negative_quantity(self):
        with self.assertRaises(InvalidQuantity):
            services.add_stock(
                household=self.household,
                product=self.product,
                quantity=Decimal("-1"),
                unit="g",
            )

    def test_add_stock_rejects_imprecise_quantity(self):
        with self.assertRaises(InvalidQuantity):
            services.add_stock(
                household=self.household,
                product=self.product,
                quantity=Decimal("0.1234"),
                unit="g",
            )

    def test_add_stock_rejects_non_numeric_quantity(self):
        with self.assertRaises(InvalidQuantity):
            services.add_stock(
                household=self.household,
                product=self.product,
                quantity="abc",
                unit="g",
            )

    def test_add_stock_rejects_float_quantity(self):
        """Floats are not exact; only Decimal / exact strings are accepted."""
        with self.assertRaises(InvalidQuantity):
            services.add_stock(
                household=self.household,
                product=self.product,
                quantity=0.1,
                unit="g",
            )

    def test_add_stock_rejects_unknown_unit(self):
        with self.assertRaises(InvalidUnit):
            services.add_stock(
                household=self.household,
                product=self.product,
                quantity=Decimal("1"),
                unit="stone",
            )

    def test_add_stock_rejects_unknown_location(self):
        with self.assertRaises(InvalidUnit):
            services.add_stock(
                household=self.household,
                product=self.product,
                quantity=Decimal("1"),
                unit="g",
                location="basement",
            )

    def test_add_stock_rejects_unit_different_from_product_unit(self):
        egg = make_product(self.household, name="Egg", unit="each")
        with self.assertRaises(UnitMismatch):
            services.add_stock(
                household=self.household,
                product=egg,
                quantity=Decimal("1"),
                unit="g",
            )

    def test_add_stock_rejects_foreign_product(self):
        _, other_household = make_household_for_user()
        foreign = make_product(other_household, name="Rival Flour")
        with self.assertRaises(HouseholdMismatch):
            services.add_stock(
                household=self.household,
                product=foreign,
                quantity=Decimal("1"),
                unit="g",
            )

    def test_rejected_add_stock_writes_nothing(self):
        with self.assertRaises(InvalidQuantity):
            services.add_stock(
                household=self.household,
                product=self.product,
                quantity=Decimal("0"),
                unit="g",
            )
        self.assertFalse(
            StockLot.objects.filter(household=self.household).exists()
        )
        self.assertEqual(InventoryEvent.objects.count(), 0)

    def test_add_stock_rolls_back_when_event_insert_fails(self):
        """The lot and its event are written in one transaction."""
        with mock.patch.object(
            InventoryEvent, "save", side_effect=RuntimeError("db down")
        ):
            with self.assertRaises(RuntimeError):
                services.add_stock(
                    household=self.household,
                    product=self.product,
                    quantity=Decimal("1"),
                    unit="g",
                )
        self.assertFalse(
            StockLot.objects.filter(household=self.household).exists()
        )
        self.assertEqual(InventoryEvent.objects.count(), 0)


class ConsumeStockServiceTests(TestCase):
    def setUp(self):
        self.user, self.household = make_household_for_user()
        self.product = make_product(self.household)
        self.lot = services.add_stock(
            household=self.household,
            product=self.product,
            quantity=Decimal("1.005"),
            unit="g",
        )

    def test_consume_reduces_balance_exactly(self):
        event = services.consume_stock(
            household=self.household,
            lot=self.lot,
            quantity=Decimal("0.005"),
            unit="g",
        )
        self.assertEqual(event.event_type, "CONSUME")
        self.assertEqual(event.quantity, Decimal("-0.005"))
        self.assertEqual(event.unit, "g")
        self.assertEqual(event.lot, self.lot)
        self.assertEqual(event.household, self.household)
        self.assertEqual(services.lot_balance(self.lot), Decimal("1.000"))

    def test_consume_can_take_the_full_balance(self):
        services.consume_stock(
            household=self.household,
            lot=self.lot,
            quantity=Decimal("1.005"),
            unit="g",
        )
        self.assertEqual(services.lot_balance(self.lot), Decimal("0.000"))
        # The lot itself still exists; only its balance is exhausted.
        self.assertTrue(StockLot.objects.filter(pk=self.lot.pk).exists())

    def test_consume_more_than_balance_rejected(self):
        with self.assertRaises(InsufficientStock):
            services.consume_stock(
                household=self.household,
                lot=self.lot,
                quantity=Decimal("1.006"),
                unit="g",
            )
        self.assertEqual(self.lot.events.count(), 1)  # only the ADD event
        self.assertEqual(services.lot_balance(self.lot), Decimal("1.005"))

    def test_consume_zero_rejected(self):
        with self.assertRaises(InvalidQuantity):
            services.consume_stock(
                household=self.household,
                lot=self.lot,
                quantity=Decimal("0"),
                unit="g",
            )

    def test_consume_negative_rejected(self):
        with self.assertRaises(InvalidQuantity):
            services.consume_stock(
                household=self.household,
                lot=self.lot,
                quantity=Decimal("-1"),
                unit="g",
            )

    def test_consume_imprecise_rejected(self):
        with self.assertRaises(InvalidQuantity):
            services.consume_stock(
                household=self.household,
                lot=self.lot,
                quantity=Decimal("0.0005"),
                unit="g",
            )

    def test_consume_unit_mismatch_rejected(self):
        with self.assertRaises(UnitMismatch):
            services.consume_stock(
                household=self.household,
                lot=self.lot,
                quantity=Decimal("1"),
                unit="kg",
            )
        self.assertEqual(self.lot.events.count(), 1)

    def test_consume_unknown_unit_rejected(self):
        with self.assertRaises(InvalidUnit):
            services.consume_stock(
                household=self.household,
                lot=self.lot,
                quantity=Decimal("1"),
                unit="stone",
            )

    def test_consume_cross_household_lot_rejected(self):
        _, other_household = make_household_for_user()
        # Acting household owns the lot, wrong household acts -> reject.
        with self.assertRaises(HouseholdMismatch):
            services.consume_stock(
                household=other_household,
                lot=self.lot,
                quantity=Decimal("1"),
                unit="g",
            )
        # Acting household is correct, lot belongs elsewhere -> reject.
        other_product = make_product(other_household, name="Their Flour")
        other_lot = services.add_stock(
            household=other_household,
            product=other_product,
            quantity=Decimal("1"),
            unit="g",
        )
        with self.assertRaises(HouseholdMismatch):
            services.consume_stock(
                household=self.household,
                lot=other_lot,
                quantity=Decimal("1"),
                unit="g",
            )
        # Neither household gained events.
        self.assertEqual(self.lot.events.count(), 1)
        self.assertEqual(other_lot.events.count(), 1)

    def test_consume_nonexistent_lot_rejected(self):
        with self.assertRaises(HouseholdMismatch):
            services.consume_stock(
                household=self.household,
                lot=StockLot(id=uuid.uuid4()),
                quantity=Decimal("1"),
                unit="g",
            )

    def test_consume_does_not_modify_lot_attributes(self):
        lot = services.add_stock(
            household=self.household,
            product=self.product,
            quantity=Decimal("2"),
            unit="g",
            location="fridge",
            expires_on=date(2026, 9, 15),
        )
        services.consume_stock(
            household=self.household,
            lot=lot,
            quantity=Decimal("0.500"),
            unit="g",
        )
        lot.refresh_from_db()
        self.assertEqual(lot.quantity, Decimal("2.000"))  # purchase size kept
        self.assertEqual(lot.location, "fridge")
        self.assertEqual(lot.expires_on, date(2026, 9, 15))
        self.assertEqual(services.lot_balance(lot), Decimal("1.500"))

    def test_consume_rolls_back_when_event_insert_fails(self):
        with mock.patch.object(
            InventoryEvent, "save", side_effect=RuntimeError("db down")
        ):
            with self.assertRaises(RuntimeError):
                services.consume_stock(
                    household=self.household,
                    lot=self.lot,
                    quantity=Decimal("0.500"),
                    unit="g",
                )
        self.assertEqual(self.lot.events.count(), 1)
        self.assertEqual(services.lot_balance(self.lot), Decimal("1.005"))


class DiscardStockServiceTests(TestCase):
    def setUp(self):
        self.user, self.household = make_household_for_user()
        self.product = make_product(self.household)
        self.lot = services.add_stock(
            household=self.household,
            product=self.product,
            quantity=Decimal("3"),
            unit="g",
        )

    def test_discard_reduces_balance_and_records_discard_event(self):
        event = services.discard_stock(
            household=self.household,
            lot=self.lot,
            quantity=Decimal("1"),
            unit="g",
        )
        self.assertEqual(event.event_type, "DISCARD")
        self.assertEqual(event.quantity, Decimal("-1.000"))
        self.assertEqual(services.lot_balance(self.lot), Decimal("2.000"))

    def test_discard_full_balance(self):
        services.discard_stock(
            household=self.household,
            lot=self.lot,
            quantity=Decimal("3"),
            unit="g",
        )
        self.assertEqual(services.lot_balance(self.lot), Decimal("0.000"))
        with self.assertRaises(InsufficientStock):
            services.discard_stock(
                household=self.household,
                lot=self.lot,
                quantity=Decimal("0.001"),
                unit="g",
            )

    def test_discard_beyond_balance_rejected(self):
        with self.assertRaises(InsufficientStock):
            services.discard_stock(
                household=self.household,
                lot=self.lot,
                quantity=Decimal("3.001"),
                unit="g",
            )
        self.assertEqual(self.lot.events.count(), 1)

    def test_discard_zero_rejected(self):
        with self.assertRaises(InvalidQuantity):
            services.discard_stock(
                household=self.household,
                lot=self.lot,
                quantity=Decimal("0"),
                unit="g",
            )

    def test_discard_unit_mismatch_rejected(self):
        with self.assertRaises(UnitMismatch):
            services.discard_stock(
                household=self.household,
                lot=self.lot,
                quantity=Decimal("1"),
                unit="ml",
            )

    def test_discard_cross_household_lot_rejected(self):
        _, other_household = make_household_for_user()
        with self.assertRaises(HouseholdMismatch):
            services.discard_stock(
                household=other_household,
                lot=self.lot,
                quantity=Decimal("1"),
                unit="g",
            )


class AdjustStockServiceTests(TestCase):
    def setUp(self):
        self.user, self.household = make_household_for_user()
        self.product = make_product(self.household)
        self.lot = services.add_stock(
            household=self.household,
            product=self.product,
            quantity=Decimal("1.000"),
            unit="g",
        )

    def test_positive_delta_increases_balance(self):
        event = services.adjust_stock(
            household=self.household,
            lot=self.lot,
            delta=Decimal("0.500"),
            unit="g",
        )
        self.assertEqual(event.event_type, "ADJUST")
        self.assertEqual(event.quantity, Decimal("0.500"))
        self.assertEqual(services.lot_balance(self.lot), Decimal("1.500"))

    def test_negative_delta_decreases_balance(self):
        event = services.adjust_stock(
            household=self.household,
            lot=self.lot,
            delta=Decimal("-0.250"),
            unit="g",
        )
        self.assertEqual(event.quantity, Decimal("-0.250"))
        self.assertEqual(services.lot_balance(self.lot), Decimal("0.750"))

    def test_zero_delta_rejected(self):
        with self.assertRaises(InvalidAdjustment):
            services.adjust_stock(
                household=self.household,
                lot=self.lot,
                delta=Decimal("0"),
                unit="g",
            )
        self.assertEqual(self.lot.events.count(), 1)

    def test_negative_delta_beyond_balance_rejected(self):
        with self.assertRaises(InsufficientStock):
            services.adjust_stock(
                household=self.household,
                lot=self.lot,
                delta=Decimal("-1.001"),
                unit="g",
            )
        self.assertEqual(self.lot.events.count(), 1)
        self.assertEqual(services.lot_balance(self.lot), Decimal("1.000"))

    def test_imprecise_delta_rejected(self):
        with self.assertRaises(InvalidQuantity):
            services.adjust_stock(
                household=self.household,
                lot=self.lot,
                delta=Decimal("0.0005"),
                unit="g",
            )

    def test_non_numeric_delta_rejected(self):
        with self.assertRaises(InvalidQuantity):
            services.adjust_stock(
                household=self.household,
                lot=self.lot,
                delta="abc",
                unit="g",
            )

    def test_unit_mismatch_rejected(self):
        with self.assertRaises(UnitMismatch):
            services.adjust_stock(
                household=self.household,
                lot=self.lot,
                delta=Decimal("0.100"),
                unit="kg",
            )

    def test_cross_household_rejected(self):
        _, other_household = make_household_for_user()
        with self.assertRaises(HouseholdMismatch):
            services.adjust_stock(
                household=other_household,
                lot=self.lot,
                delta=Decimal("0.100"),
                unit="g",
            )

    def test_adjust_can_zero_the_balance(self):
        services.adjust_stock(
            household=self.household,
            lot=self.lot,
            delta=Decimal("-1.000"),
            unit="g",
        )
        self.assertEqual(services.lot_balance(self.lot), Decimal("0.000"))


class BalanceSemanticsTests(TestCase):
    def setUp(self):
        self.user, self.household = make_household_for_user()
        self.product = make_product(self.household)

    def test_balance_is_derived_from_events_not_lot_quantity(self):
        lot = services.add_stock(
            household=self.household,
            product=self.product,
            quantity=Decimal("5"),
            unit="g",
        )
        services.consume_stock(
            household=self.household,
            lot=lot,
            quantity=Decimal("2"),
            unit="g",
        )
        lot.refresh_from_db()
        self.assertEqual(lot.quantity, Decimal("5.000"))  # purchase size kept
        self.assertEqual(services.lot_balance(lot), Decimal("3.000"))

    def test_balance_is_exact_decimal_not_float(self):
        """The classic float trap: 0.1 + 0.2 must be exactly 0.300."""
        lot = services.add_stock(
            household=self.household,
            product=self.product,
            quantity=Decimal("0.100"),
            unit="g",
        )
        services.adjust_stock(
            household=self.household,
            lot=lot,
            delta=Decimal("0.200"),
            unit="g",
        )
        self.assertEqual(str(services.lot_balance(lot)), "0.300")

    def test_new_lot_without_events_has_zero_balance(self):
        lot = StockLot.objects.create(
            household=self.household,
            product=self.product,
            quantity=Decimal("4"),
            unit="g",
        )
        self.assertEqual(services.lot_balance(lot), Decimal("0"))

    def test_lots_of_same_product_are_independent(self):
        lot_a = services.add_stock(
            household=self.household,
            product=self.product,
            quantity=Decimal("2"),
            unit="g",
        )
        lot_b = services.add_stock(
            household=self.household,
            product=self.product,
            quantity=Decimal("2"),
            unit="g",
        )
        services.consume_stock(
            household=self.household,
            lot=lot_a,
            quantity=Decimal("2"),
            unit="g",
        )
        self.assertEqual(services.lot_balance(lot_a), Decimal("0.000"))
        self.assertEqual(services.lot_balance(lot_b), Decimal("2.000"))

    def test_mixed_event_signs_sum_to_derived_balance(self):
        lot = services.add_stock(
            household=self.household,
            product=self.product,
            quantity=Decimal("4"),
            unit="g",
        )
        services.consume_stock(
            household=self.household, lot=lot, quantity=Decimal("1"), unit="g"
        )
        services.discard_stock(
            household=self.household, lot=lot, quantity=Decimal("1.500"),
            unit="g",
        )
        services.adjust_stock(
            household=self.household,
            lot=lot,
            delta=Decimal("0.500"),
            unit="g",
        )
        self.assertEqual(services.lot_balance(lot), Decimal("2.000"))
        self.assertEqual(lot.events.count(), 4)


class LockingAndValidationTests(TestCase):
    def setUp(self):
        self.user, self.household = make_household_for_user()
        self.product = make_product(self.household)
        self.lot = services.add_stock(
            household=self.household,
            product=self.product,
            quantity=Decimal("2"),
            unit="g",
        )

    def test_mutations_issue_row_lock_on_supported_backends(self):
        """On backends with locking reads, the service must lock the lot row.

        SQLite does not support SELECT ... FOR UPDATE, so the assertion is
        skipped there; PostgreSQL (the production backend) exercises it.
        """
        if not connection.features.has_select_for_update:
            self.skipTest(
                "select_for_update is not supported by the test database"
            )
        with CaptureQueriesContext(connection) as ctx:
            services.consume_stock(
                household=self.household,
                lot=self.lot,
                quantity=Decimal("1"),
                unit="g",
            )
        locking_queries = [
            query["sql"]
            for query in ctx.captured_queries
            if "FOR UPDATE" in query["sql"].upper()
        ]
        self.assertTrue(
            locking_queries,
            "consume_stock did not issue a SELECT ... FOR UPDATE lock",
        )

    def test_service_events_are_validated_before_insertion(self):
        """Imprecise input must be rejected before any event row exists."""
        with self.assertRaises(InvalidQuantity):
            services.consume_stock(
                household=self.household,
                lot=self.lot,
                quantity=Decimal("0.0001"),
                unit="g",
            )
        self.assertEqual(self.lot.events.count(), 1)

    def test_service_events_are_append_only(self):
        event = services.consume_stock(
            household=self.household,
            lot=self.lot,
            quantity=Decimal("0.500"),
            unit="g",
        )
        event.quantity = Decimal("9.999")
        with self.assertRaises(ValueError):
            event.save()

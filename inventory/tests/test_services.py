"""Service tests for add_stock / consume_stock / discard_stock / adjust_stock,
plus resolve_product and set_lot_balance.

Covers positive and exact-decimal inputs, signed-event semantics, household
isolation, exact unit compatibility, no-negative-balance enforcement,
transaction rollback on failure, row-lock usage on backends that support
locking reads, preservation of lot attributes (location, dates), serialized
same-household product resolution, and lock-ordered observed-balance
correction.
"""

import uuid
from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models.query import QuerySet
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from inventory import services
from inventory.exceptions import (
    AllocationMismatch,
    DuplicateMealEvent,
    HouseholdMismatch,
    InsufficientStock,
    InvalidAdjustment,
    InvalidQuantity,
    InvalidUnit,
    SuggestionNotCookable,
    UnitMismatch,
)
from inventory.models import (
    Household,
    InventoryEvent,
    MealEvent,
    MealIngredient,
    MealSuggestion,
    Product,
    StockLot,
)


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


class ProductResolutionServiceTests(TestCase):
    """resolve_product: normalized case-insensitive reuse, household
    serialization, unit-conflict rejection, validated creation, rollback."""

    def setUp(self):
        self.user, self.household = make_household_for_user()

    def test_creates_product_with_normalized_name(self):
        product = services.resolve_product(
            household=self.household,
            raw_name=" \t\n green   bean \n ",
            unit="count",
        )
        self.assertEqual(product.name, "green bean")
        self.assertEqual(product.unit, "count")
        self.assertEqual(product.household, self.household)
        self.assertEqual(
            Product.objects.filter(
                household=self.household, name="green bean"
            ).count(),
            1,
        )

    def test_reuses_existing_product_case_insensitively(self):
        make_product(self.household, name="Tomato", unit="count")
        product = services.resolve_product(
            household=self.household, raw_name="  tOMATO ", unit="count"
        )
        self.assertEqual(product.pk, Product.objects.get(name="Tomato").pk)
        self.assertEqual(
            Product.objects.filter(
                household=self.household, name__iexact="tomato"
            ).count(),
            1,
        )

    def test_unit_conflict_rejected_without_writes(self):
        make_product(self.household, name="Flour", unit="g")
        with self.assertRaises(UnitMismatch) as ctx:
            services.resolve_product(
                household=self.household, raw_name="Flour", unit="ml"
            )
        self.assertIn("already exists", str(ctx.exception))
        self.assertEqual(
            Product.objects.filter(household=self.household).count(), 1
        )

    def test_empty_name_rejected(self):
        with self.assertRaises(ValueError):
            services.resolve_product(
                household=self.household, raw_name="   ", unit="count"
            )
        self.assertEqual(Product.objects.count(), 0)

    def test_unknown_unit_rejected(self):
        with self.assertRaises(InvalidUnit):
            services.resolve_product(
                household=self.household, raw_name="Rice", unit="stone"
            )
        self.assertEqual(Product.objects.count(), 0)

    def test_created_product_is_validated(self):
        """A name the model rejects must raise before any row exists."""
        with self.assertRaises(ValidationError):
            services.resolve_product(
                household=self.household, raw_name="x" * 300, unit="count"
            )
        self.assertEqual(Product.objects.count(), 0)

    def test_unit_conflict_rolls_back_inside_caller_transaction(self):
        make_product(self.household, name="Flour", unit="g")
        with self.assertRaises(UnitMismatch):
            with transaction.atomic():
                services.resolve_product(
                    household=self.household, raw_name="Flour", unit="ml"
                )
        self.assertEqual(
            Product.objects.filter(
                household=self.household, name__iexact="flour", unit="ml"
            ).count(),
            0,
        )

    def test_serialized_resolution_creates_exactly_one_product(self):
        """Simulate two same-household resolutions racing on a new product.

        The second resolution is injected at the moment the first takes its
        household lock. On PostgreSQL the injected call blocks on that lock
        until the first transaction commits and then reuses the created
        row; on SQLite (locking reads are no-ops, same connection) it
        completes synchronously inside the first call. Either way, exactly
        one product may exist.
        """
        real_sfu = QuerySet.select_for_update
        state = {"injected": False}
        household = self.household

        def fake_sfu(queryset, *args, **kwargs):
            if not state["injected"] and queryset.model is Household:
                state["injected"] = True
                services.resolve_product(
                    household=household,
                    raw_name="  bAsIl ",
                    unit="count",
                )
            return real_sfu(queryset, *args, **kwargs)

        with mock.patch.object(QuerySet, "select_for_update", fake_sfu):
            first = services.resolve_product(
                household=self.household, raw_name="Basil", unit="count"
            )

        matches = Product.objects.filter(
            household=self.household, name__iexact="basil"
        )
        self.assertEqual(matches.count(), 1)
        self.assertEqual(matches.first().pk, first.pk)
        # The winner's spelling is stored; the loser reuses it. On SQLite the
        # injected call completes first (locks are no-ops, same connection),
        # so "bAsIl" wins; on PostgreSQL the outer caller would win. Either
        # way there is exactly one product and both callers got the same row.
        self.assertIn(first.name, ("Basil", "bAsIl"))


class SetLotBalanceServiceTests(TestCase):
    """set_lot_balance: lock-ordered delta, no-op/negative/imprecise
    rejection, cross-household isolation, rollback, and protection against
    an intervening mutation landing at the lock point."""

    def setUp(self):
        self.user, self.household = make_household_for_user()
        self.product = make_product(self.household)
        self.lot = services.add_stock(
            household=self.household,
            product=self.product,
            quantity=Decimal("5"),
            unit="g",
        )

    def test_increase_appends_positive_adjust(self):
        event = services.set_lot_balance(
            household=self.household,
            lot=self.lot,
            observed_balance=Decimal("6.5"),
            note="counted more",
        )
        self.assertEqual(event.event_type, "ADJUST")
        self.assertEqual(event.quantity, Decimal("1.500"))
        self.assertEqual(event.note, "counted more")
        self.assertEqual(services.lot_balance(self.lot), Decimal("6.500"))

    def test_decrease_appends_negative_adjust(self):
        event = services.set_lot_balance(
            household=self.household,
            lot=self.lot,
            observed_balance=Decimal("0.25"),
        )
        self.assertEqual(event.quantity, Decimal("-4.750"))
        self.assertEqual(services.lot_balance(self.lot), Decimal("0.250"))

    def test_zero_observed_decreases_balance_to_zero(self):
        event = services.set_lot_balance(
            household=self.household,
            lot=self.lot,
            observed_balance=Decimal("0"),
        )
        self.assertEqual(event.quantity, Decimal("-5.000"))
        self.assertEqual(services.lot_balance(self.lot), Decimal("0.000"))

    def test_no_op_observed_rejected_without_event(self):
        with self.assertRaises(InvalidAdjustment) as ctx:
            services.set_lot_balance(
                household=self.household,
                lot=self.lot,
                observed_balance=Decimal("5"),
            )
        self.assertIn("No-op", str(ctx.exception))
        self.assertEqual(self.lot.events.count(), 1)
        self.assertEqual(services.lot_balance(self.lot), Decimal("5.000"))

    def test_negative_observed_rejected(self):
        with self.assertRaises(InvalidQuantity):
            services.set_lot_balance(
                household=self.household,
                lot=self.lot,
                observed_balance=Decimal("-0.5"),
            )
        self.assertEqual(self.lot.events.count(), 1)

    def test_imprecise_observed_rejected(self):
        with self.assertRaises(InvalidQuantity) as ctx:
            services.set_lot_balance(
                household=self.household,
                lot=self.lot,
                observed_balance="5.0005",
            )
        self.assertIn("3 decimal places", str(ctx.exception))
        self.assertEqual(self.lot.events.count(), 1)

    def test_foreign_household_lot_rejected(self):
        _, other_household = make_household_for_user()
        with self.assertRaises(HouseholdMismatch):
            services.set_lot_balance(
                household=other_household,
                lot=self.lot,
                observed_balance=Decimal("6"),
            )
        self.assertEqual(self.lot.events.count(), 1)

    def test_unknown_lot_rejected(self):
        with self.assertRaises(HouseholdMismatch):
            services.set_lot_balance(
                household=self.household,
                lot=StockLot(pk=uuid.uuid4(), household=self.household),
                observed_balance=Decimal("6"),
            )

    def test_intervening_mutation_cannot_produce_wrong_final_balance(self):
        """A mutation that lands exactly as the lot lock is taken must still
        leave the lot at exactly the observed balance.

        The pre-correction defect read the balance *before* the lock and
        derived the delta from that stale read. This test injects a
        competing CONSUME at the lock point: a stale pre-lock read (5.000)
        would have produced delta +2.000 and a final balance of 5.000, not
        the observed 7.000. The service derives the delta after the lock,
        so the delta is +3.000 and the final balance is exactly the
        observed value.
        """
        real_sfu = QuerySet.select_for_update
        state = {"injected": False}
        household = self.household
        lot = self.lot

        def fake_sfu(queryset, *args, **kwargs):
            if not state["injected"] and queryset.model is StockLot:
                state["injected"] = True
                services.consume_stock(
                    household=household,
                    lot=lot,
                    quantity=Decimal("1"),
                    unit="g",
                )
            return real_sfu(queryset, *args, **kwargs)

        with mock.patch.object(QuerySet, "select_for_update", fake_sfu):
            event = services.set_lot_balance(
                household=self.household,
                lot=self.lot,
                observed_balance=Decimal("7"),
                note="counted at lock time",
            )

        self.assertEqual(services.lot_balance(self.lot), Decimal("7.000"))
        self.assertEqual(event.quantity, Decimal("3.000"))
        self.assertEqual(event.note, "counted at lock time")

    def test_later_failure_in_caller_transaction_rolls_back_adjust(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                services.set_lot_balance(
                    household=self.household,
                    lot=self.lot,
                    observed_balance=Decimal("9"),
                    note="counted",
                )
                raise RuntimeError("simulated downstream failure")
        self.assertEqual(services.lot_balance(self.lot), Decimal("5.000"))
        self.assertEqual(self.lot.events.count(), 1)


# --- confirm_cook -------------------------------------------------------------


def make_suggestion(
    household,
    *,
    title="Stir Fry",
    status=MealSuggestion.Status.SUGGESTED,
):
    """Create a cookable suggestion with the given status."""
    return MealSuggestion.objects.create(
        household=household,
        status=status,
        title=title,
        servings=2,
        time_minutes=20,
    )


def make_ingredient(
    suggestion,
    household,
    *,
    name="Tomato",
    unit="g",
    required,
    owned=None,
    missing=Decimal("0"),
    allocations=None,
):
    """Create one immutable ingredient snapshot (owned defaults to required)."""
    owned = required if owned is None else owned
    return MealIngredient.objects.create(
        suggestion=suggestion,
        household=household,
        name=name,
        unit=unit,
        required_quantity=required,
        owned_quantity=owned,
        missing_quantity=missing,
        allocations=allocations if allocations is not None else [],
    )


class ConfirmCookServiceTests(TestCase):
    """confirm_cook: atomic allocation, deterministic lock/event order,
    tamper-proof validation, exact-once semantics, and zero-write rollback
    on every failure path."""

    def setUp(self):
        self.user, self.household = make_household_for_user()
        self.product = make_product(self.household, name="Tomato", unit="g")
        # Two lots for the same product so multi-lot aggregation can be
        # exercised in deterministic UUID order.
        self.lot_a = services.add_stock(
            household=self.household,
            product=self.product,
            quantity=Decimal("3.000"),
            unit="g",
        )
        self.lot_b = services.add_stock(
            household=self.household,
            product=self.product,
            quantity=Decimal("2.000"),
            unit="g",
        )
        self.other_user, self.other_household = make_household_for_user()
        self.other_product = make_product(self.other_household, name="Tomato")
        self.other_lot = services.add_stock(
            household=self.other_household,
            product=self.other_product,
            quantity=Decimal("5.000"),
            unit="g",
        )

    def _event_count(self):
        """Household's InventoryEvent rows (setUp adds two ADD events)."""
        return InventoryEvent.objects.filter(household=self.household).count()

    # -- happy paths -----------------------------------------------------------

    def test_partial_single_lot_happy_path(self):
        suggestion = make_suggestion(self.household)
        take = Decimal("1.500")
        make_ingredient(
            suggestion,
            self.household,
            required=take,
            allocations=[{"lot": str(self.lot_a.pk), "quantity": str(take)}],
        )
        event = services.confirm_cook(
            household=self.household, suggestion=suggestion
        )
        self.assertIsInstance(event, MealEvent)
        self.assertEqual(event.household, self.household)
        self.assertEqual(event.suggestion, suggestion)
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, MealSuggestion.Status.COOKED)
        consume = self.lot_a.events.get(event_type=InventoryEvent.EventType.CONSUME)
        self.assertEqual(consume.quantity, -take)
        self.assertEqual(consume.unit, "g")
        self.assertEqual(services.lot_balance(self.lot_a), Decimal("1.500"))
        self.assertEqual(services.lot_balance(self.lot_b), Decimal("2.000"))
        self.assertTrue(consume.note)  # bounded meal-reference note
        self.assertLessEqual(len(consume.note), 200)

    def test_multiple_lot_aggregate_deduction_sorted_order(self):
        """Two ingredients drawing from both lots must aggregate per lot,
        lock lots in sorted UUID order, and emit events in that order."""
        suggestion = make_suggestion(self.household)
        lot_a, lot_b = self.lot_a.pk, self.lot_b.pk
        make_ingredient(
            suggestion,
            self.household,
            required=Decimal("2.000"),
            allocations=[
                {"lot": str(lot_a), "quantity": "1.000"},
                {"lot": str(lot_b), "quantity": "1.000"},
            ],
        )
        make_ingredient(
            suggestion,
            self.household,
            name="Pepper",
            required=Decimal("3.000"),
            allocations=[
                {"lot": str(lot_a), "quantity": "2.000"},
                {"lot": str(lot_b), "quantity": "1.000"},
            ],
        )
        # lot_a: 1.000 (tomato) + 2.000 (pepper) = 3.000 == balance.
        # lot_b: 1.000 (tomato) + 1.000 (pepper) = 2.000 == balance.
        services.confirm_cook(household=self.household, suggestion=suggestion)
        # Per-lot aggregate deductions: lot_a 3.000, lot_b 2.000.
        self.assertEqual(services.lot_balance(self.lot_a), Decimal("0.000"))
        self.assertEqual(services.lot_balance(self.lot_b), Decimal("0.000"))
        # Exactly one CONSUME event per lot, in deterministic UUID order.
        events = list(
            InventoryEvent.objects.filter(
                household=self.household,
                event_type=InventoryEvent.EventType.CONSUME,
            ).order_by("id")
        )
        self.assertEqual(len(events), 2)
        # The per-lot aggregate deductions must be exact regardless of
        # physical row order in the test DB.
        by_lot = {e.lot_id: e.quantity for e in events}
        self.assertEqual(by_lot[lot_a], -Decimal("3.000"))
        self.assertEqual(by_lot[lot_b], -Decimal("2.000"))
        # Deterministic lock/event order (sorted by UUID string) is a
        # backend-relevant guarantee: on backends that actually serialize
        # locking reads, the events must be inserted in that order.
        expected_order = sorted([lot_a, lot_b], key=str)
        # Physical insertion order (SQLite rowid) is deterministic even when
        # the pk is a random UUID, so prove the sorted-UUID CONSUME order on
        # every backend — ungated from has_select_for_update.
        # SQLite stores UUIDField values as 32-char hex (no dashes), so the
        # raw WHERE clause binds the .hex form and the returned lot ids are
        # normalized back through uuid.UUID.
        table = InventoryEvent._meta.db_table
        order_rows = connection.cursor().execute(
            f"SELECT lot_id FROM {table} "
            "WHERE household_id = ? AND event_type = 'CONSUME' "
            "ORDER BY rowid",
            [self.household.pk.hex],
        ).fetchall()
        self.assertEqual(
            [uuid.UUID(row[0]) for row in order_rows],
            [uuid.UUID(str(lot)) for lot in expected_order],
        )
        # Row-lock SQL is only issued on backends that support
        # select_for_update; keep that assertion backend-gated.
        if connection.features.has_select_for_update:
            self.assertEqual([e.lot_id for e in events], expected_order)

    # -- rejection before any write --------------------------------------------

    def test_tampered_ingredient_household_rejected_before_writes(self):
        """Bishop hardening: a snapshot row whose household differs from the
        locked suggestion/caller household is a tampered snapshot and must be
        rejected before any write — even when its allocations reference the
        caller's own lots."""
        suggestion = self._snapshot_with(
            allocations=[{"lot": str(self.lot_a.pk), "quantity": "1.000"}],
        )
        # Forge the snapshot row via raw SQL: MealIngredient.save() refuses
        # ORM updates, which is exactly the tampering surface this check
        # must defend.
        table = MealIngredient._meta.db_table
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {table} SET household_id = ? "
                "WHERE id = ?",
                [self.other_household.pk.hex,
                 suggestion.ingredients.get().pk.hex],
            )
        before_events = self._event_count()
        with self.assertRaises(HouseholdMismatch):
            services.confirm_cook(
                household=self.household, suggestion=suggestion
            )
        self.assertEqual(self._event_count(), before_events)
        self.assertEqual(MealEvent.objects.count(), 0)
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, MealSuggestion.Status.SUGGESTED)
        self.assertEqual(services.lot_balance(self.lot_a), Decimal("3.000"))

    def test_foreign_suggestion_rejected(self):
        suggestion = make_suggestion(self.other_household)
        make_ingredient(
            suggestion,
            self.other_household,
            required=Decimal("1.000"),
            allocations=[{"lot": str(self.other_lot.pk), "quantity": "1.000"}],
        )
        before_events = self._event_count()
        with self.assertRaises(HouseholdMismatch):
            services.confirm_cook(
                household=self.household, suggestion=suggestion
            )
        self.assertEqual(self._event_count(), before_events)
        self.assertEqual(MealEvent.objects.count(), 0)

    def test_unknown_suggestion_rejected(self):
        # A suggestion that belongs to another household.
        ghost = make_suggestion(self.other_household)
        with self.assertRaises(HouseholdMismatch):
            services.confirm_cook(
                household=self.household, suggestion=ghost
            )
        # And a pk that exists for no household at all (bare UUID).
        with self.assertRaises(HouseholdMismatch):
            services.confirm_cook(
                household=self.household,
                suggestion=uuid.UUID(str(uuid.uuid4())),
            )

    def test_rejected_status_rejected(self):
        suggestion = make_suggestion(
            self.household, status=MealSuggestion.Status.REJECTED
        )
        make_ingredient(
            suggestion,
            self.household,
            required=Decimal("1.000"),
            allocations=[{"lot": str(self.lot_a.pk), "quantity": "1.000"}],
        )
        before_events = self._event_count()
        with self.assertRaises(SuggestionNotCookable):
            services.confirm_cook(
                household=self.household, suggestion=suggestion
            )
        self.assertEqual(self._event_count(), before_events)
        self.assertEqual(MealEvent.objects.count(), 0)

    def test_missing_ingredient_rejected(self):
        suggestion = make_suggestion(self.household)
        make_ingredient(
            suggestion,
            self.household,
            required=Decimal("5.000"),
            owned=Decimal("3.000"),
            missing=Decimal("2.000"),
            allocations=[{"lot": str(self.lot_a.pk), "quantity": "3.000"}],
        )
        with self.assertRaises(SuggestionNotCookable):
            services.confirm_cook(
                household=self.household, suggestion=suggestion
            )
        self.assertEqual(self._event_count(), 2)

    def test_empty_ingredient_snapshot_rejected(self):
        suggestion = make_suggestion(self.household)
        with self.assertRaises(AllocationMismatch):
            services.confirm_cook(
                household=self.household, suggestion=suggestion
            )
        self.assertEqual(self._event_count(), 2)

    # -- tamper-proof allocation validation ------------------------------------

    def _snapshot_with(self, *, name="Tomato", required=Decimal("1.000"),
                       allocations=None):
        suggestion = make_suggestion(self.household)
        make_ingredient(
            suggestion,
            self.household,
            name=name,
            required=required,
            allocations=allocations,
        )
        return suggestion

    def test_malformed_allocation_not_a_list(self):
        suggestion = self._snapshot_with(allocations="bogus")
        with self.assertRaises(AllocationMismatch):
            services.confirm_cook(
                household=self.household, suggestion=suggestion
            )
        self.assertEqual(self._event_count(), 2)

    def test_malformed_allocation_entry_not_a_dict(self):
        suggestion = self._snapshot_with(allocations=["nope"])
        with self.assertRaises(AllocationMismatch):
            services.confirm_cook(
                household=self.household, suggestion=suggestion
            )
        self.assertEqual(self._event_count(), 2)

    def test_malformed_lot_uuid_rejected(self):
        suggestion = self._snapshot_with(
            allocations=[{"lot": "not-a-uuid", "quantity": "1.000"}]
        )
        with self.assertRaises(AllocationMismatch):
            services.confirm_cook(
                household=self.household, suggestion=suggestion
            )
        self.assertEqual(self._event_count(), 2)

    def test_malformed_allocation_quantity_rejected(self):
        for bad in ("abc", "NaN", "Infinity", "0.0001"):
            suggestion = self._snapshot_with(
                allocations=[{"lot": str(self.lot_a.pk), "quantity": bad}]
            )
            with self.assertRaises(InvalidQuantity):
                services.confirm_cook(
                    household=self.household, suggestion=suggestion
                )
            self.assertEqual(self._event_count(), 2)

    def test_nonpositive_allocation_quantity_rejected(self):
        suggestion = self._snapshot_with(
            allocations=[{"lot": str(self.lot_a.pk), "quantity": "0"}]
        )
        with self.assertRaises(InvalidQuantity):
            services.confirm_cook(
                household=self.household, suggestion=suggestion
            )

    def test_allocation_total_mismatch_rejected(self):
        # Owned/required say 2.000 but allocations sum to 1.500.
        suggestion = self._snapshot_with(
            required=Decimal("2.000"),
            allocations=[{"lot": str(self.lot_a.pk), "quantity": "1.500"}],
        )
        with self.assertRaises(AllocationMismatch):
            services.confirm_cook(
                household=self.household, suggestion=suggestion
            )
        self.assertEqual(self._event_count(), 2)

    def test_same_lot_two_units_rejected(self):
        """A lot allocated under two different units is a tampered snapshot."""
        suggestion = make_suggestion(self.household)
        make_ingredient(
            suggestion,
            self.household,
            name="Tomato",
            unit="g",
            required=Decimal("1.000"),
            allocations=[{"lot": str(self.lot_a.pk), "quantity": "1.000"}],
        )
        make_ingredient(
            suggestion,
            self.household,
            name="Tomato",
            unit="ml",
            required=Decimal("1.000"),
            allocations=[{"lot": str(self.lot_a.pk), "quantity": "1.000"}],
        )
        with self.assertRaises(UnitMismatch):
            services.confirm_cook(
                household=self.household, suggestion=suggestion
            )
        self.assertEqual(self._event_count(), 2)

    # -- lot-level failures under lock ------------------------------------------

    def test_foreign_lot_rejected(self):
        suggestion = self._snapshot_with(
            allocations=[{"lot": str(self.other_lot.pk), "quantity": "1.000"}]
        )
        with self.assertRaises(HouseholdMismatch):
            services.confirm_cook(
                household=self.household, suggestion=suggestion
            )
        self.assertEqual(self._event_count(), 2)

    def test_unit_mismatch_with_live_lot_rejected(self):
        """Snapshot says 'ml' but the live lot's unit is 'g'."""
        suggestion = make_suggestion(self.household)
        make_ingredient(
            suggestion,
            self.household,
            unit="ml",
            required=Decimal("1.000"),
            allocations=[{"lot": str(self.lot_a.pk), "quantity": "1.000"}],
        )
        with self.assertRaises(UnitMismatch):
            services.confirm_cook(
                household=self.household, suggestion=suggestion
            )
        self.assertEqual(self._event_count(), 2)

    def test_insufficient_live_balance_rejected(self):
        """Snapshot was valid at proposal time, but a concurrent consume
        drained the lot — the live balance check must fail closed."""
        suggestion = self._snapshot_with(
            required=Decimal("3.000"),
            allocations=[{"lot": str(self.lot_a.pk), "quantity": "3.000"}],
        )
        # Drain lot_a after the snapshot was taken.
        services.consume_stock(
            household=self.household,
            lot=self.lot_a,
            quantity=Decimal("2.000"),
            unit="g",
        )
        self.assertEqual(services.lot_balance(self.lot_a), Decimal("1.000"))
        with self.assertRaises(InsufficientStock):
            services.confirm_cook(
                household=self.household, suggestion=suggestion
            )
        # No cook deduction happened: only the two setup ADD events plus the
        # one deliberate drain CONSUME exist for this household.
        self.assertEqual(self._event_count(), 3)
        self.assertEqual(services.lot_balance(self.lot_a), Decimal("1.000"))

    # -- exactly-once semantics --------------------------------------------------

    def test_sequential_duplicate_rejected_no_second_deduction(self):
        suggestion = self._snapshot_with(
            required=Decimal("1.000"),
            allocations=[{"lot": str(self.lot_a.pk), "quantity": "1.000"}],
        )
        first = services.confirm_cook(
            household=self.household, suggestion=suggestion
        )
        self.assertIsInstance(first, MealEvent)
        balance_after_first = services.lot_balance(self.lot_a)
        with self.assertRaises(DuplicateMealEvent):
            services.confirm_cook(
                household=self.household, suggestion=suggestion
            )
        self.assertEqual(
            services.lot_balance(self.lot_a), balance_after_first
        )
        self.assertEqual(self._event_count(), 3)
        self.assertEqual(MealEvent.objects.filter(suggestion=suggestion).count(), 1)

    # -- rollback on mid-transaction failure -------------------------------------

    def test_failure_after_first_event_rolls_back_all(self):
        """Forcing a failure between the first CONSUME event and the
        MealEvent must leave the ledger exactly as it was: zero events,
        unchanged balances, no cook record, unchanged status."""
        suggestion = self._snapshot_with(
            required=Decimal("1.000"),
            allocations=[{"lot": str(self.lot_a.pk), "quantity": "1.000"}],
        )
        real_make_event = services._make_event
        state = {"calls": 0}

        def failing_make_event(*args, **kwargs):
            state["calls"] += 1
            try:
                return real_make_event(*args, **kwargs)
            finally:
                if state["calls"] == 1:
                    # Fail right after the first (only) event is written but
                    # before MealEvent creation.
                    raise RuntimeError("simulated crash after first event")

        with mock.patch.object(
            services, "_make_event", side_effect=failing_make_event
        ):
            with self.assertRaises(RuntimeError):
                services.confirm_cook(
                    household=self.household, suggestion=suggestion
                )
        self.assertEqual(self._event_count(), 2)
        self.assertEqual(services.lot_balance(self.lot_a), Decimal("3.000"))
        self.assertEqual(MealEvent.objects.count(), 0)
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, MealSuggestion.Status.SUGGESTED)

    def test_intervention_at_lock_boundary_still_correct(self):
        """A competing mutation that lands exactly as the lot lock is taken
        must not corrupt the deduction: the balance is recomputed under
        lock, so the final state is exact either way."""
        suggestion = self._snapshot_with(
            required=Decimal("1.000"),
            allocations=[{"lot": str(self.lot_a.pk), "quantity": "1.000"}],
        )
        real_sfu = QuerySet.select_for_update
        state = {"injected": False}
        household, lot = self.household, self.lot_a

        def fake_sfu(queryset, *args, **kwargs):
            if not state["injected"] and queryset.model is StockLot:
                state["injected"] = True
                # Simulate a competing add that races the lock boundary.
                services.add_stock(
                    household=household,
                    product=self.product,
                    quantity=Decimal("1.000"),
                    unit="g",
                )
            return real_sfu(queryset, *args, **kwargs)

        with mock.patch.object(QuerySet, "select_for_update", fake_sfu):
            services.confirm_cook(
                household=self.household, suggestion=suggestion
            )
        # lot_a: 3.000 - 1.000 (cook deduction under lock) = 2.000.
        # The racing add created a *new* lot (1.000), so lot_a's balance
        # must reflect only the cook deduction — the lock boundary cannot
        # double-count or miss the race.
        self.assertEqual(services.lot_balance(lot), Decimal("2.000"))
        self.assertEqual(
            len(self.household.lots.filter(unit="g", product=self.product)),
            3,  # lot_a, lot_b, and the race-added lot
        )
        self.assertEqual(
            lot.events.filter(
                event_type=InventoryEvent.EventType.CONSUME
            ).count(),
            1,
        )

    # -- determinism and validation plumbing --------------------------------------

    def test_consume_events_carry_bounded_note(self):
        suggestion = self._snapshot_with(
            required=Decimal("1.000"),
            allocations=[{"lot": str(self.lot_a.pk), "quantity": "1.000"}],
        )
        services.confirm_cook(
            household=self.household, suggestion=suggestion
        )
        events = list(
            InventoryEvent.objects.filter(household=self.household).filter(
                event_type=InventoryEvent.EventType.CONSUME
            )
        )
        for event in events:
            self.assertEqual(len(event.note), len(event.note[:200]))
            self.assertIn(str(suggestion.pk), event.note)

    def test_row_locks_issued_on_supported_backends(self):
        if not connection.features.has_select_for_update:
            self.skipTest(
                "select_for_update is not supported by the test database"
            )
        suggestion = self._snapshot_with(
            required=Decimal("1.000"),
            allocations=[{"lot": str(self.lot_a.pk), "quantity": "1.000"}],
        )
        with CaptureQueriesContext(connection) as ctx:
            services.confirm_cook(
                household=self.household, suggestion=suggestion
            )
        locking_queries = [
            query["sql"]
            for query in ctx.captured_queries
            if "FOR UPDATE" in query["sql"].upper()
        ]
        # One suggestion lock + one lot lock.
        self.assertEqual(len(locking_queries), 2)

    def test_unknown_unit_in_snapshot_rejected(self):
        """A snapshot row bypassing form validation (e.g. ORM-level
        tampering) must still be rejected by the service before any write."""
        suggestion = make_suggestion(self.household)
        # Bypasses model-level validators by writing the row directly.
        MealIngredient.objects.create(
            suggestion=suggestion,
            household=self.household,
            name="Mystery",
            unit="cubits",
            required_quantity=Decimal("1.000"),
            owned_quantity=Decimal("1.000"),
            missing_quantity=Decimal("0"),
            allocations=[{"lot": str(self.lot_a.pk), "quantity": "1.000"}],
        )
        # Refresh so the in-memory snapshot carries the tampered unit.
        suggestion.refresh_from_db()
        try:
            services.confirm_cook(
                household=self.household, suggestion=suggestion
            )
            self.fail("Expected InvalidUnit for unknown snapshot unit")
        except InvalidUnit:
            pass
        self.assertEqual(self._event_count(), 2)

    def test_later_failure_in_caller_transaction_rolls_back_cook(self):
        suggestion = self._snapshot_with(
            required=Decimal("1.000"),
            allocations=[{"lot": str(self.lot_a.pk), "quantity": "1.000"}],
        )
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                services.confirm_cook(
                    household=self.household, suggestion=suggestion
                )
                raise RuntimeError("simulated downstream failure")
        self.assertEqual(self._event_count(), 2)
        self.assertEqual(MealEvent.objects.count(), 0)
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, MealSuggestion.Status.SUGGESTED)

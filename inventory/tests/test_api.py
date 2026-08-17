"""API tests: auth/CSRF boundaries, representation, list filters,
mutations, household isolation, and rollback behavior.

All writes go through the API views (service-only writes); fixture setup
uses the service layer directly.
"""

import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from inventory import services
from inventory.models import Product, StockLot

User = get_user_model()
PASSWORD = "sup3r-s3cr3t-pass"

LOTS = "api:lots_list"
LOT = "api:lot_detail"
LOT_EVENTS = "api:lot_events"
LOT_CONSUME = "api:lot_consume"
LOT_DISCARD = "api:lot_discard"
LOT_CORRECT = "api:lot_correct"


def make_user(username):
    return User.objects.create_user(username=username, password=PASSWORD)


def login(client, user):
    assert client.login(username=user.username, password=PASSWORD)


def make_lot(user, name, quantity, unit="count", **kwargs):
    """Create a product + lot via the service layer (fixture helper)."""
    household = user.household
    product, _ = Product.objects.get_or_create(
        household=household, name=name, defaults={"unit": unit}
    )
    return services.add_stock(
        household=household,
        product=product,
        quantity=Decimal(quantity),
        unit=unit,
        **kwargs,
    )


def error_body(response):
    """Extract the stable error envelope from a response."""
    return response.json().get("error")


class AuthBoundaryTests(TestCase):
    """Unauthenticated and CSRF-failed requests return stable JSON
    envelopes with no writes."""

    def test_anonymous_get_lists_401_envelope(self):
        client = Client()
        user = make_user("alice")
        make_lot(user, "apples", "5")
        response = client.get(reverse(LOTS))
        # SessionAuthentication coerces NotAuthenticated to 403 when no
        # WWW-Authenticate header is advertised (the DRF default).
        self.assertEqual(response.status_code, 403)
        body = error_body(response)
        self.assertEqual(body["code"], "not_authenticated")
        self.assertIsInstance(body["fields"], dict)

    def test_anonymous_get_detail_401_envelope(self):
        client = Client()
        user = make_user("alice")
        lot = make_lot(user, "apples", "5")
        response = client.get(reverse(LOT, args=[lot.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(error_body(response)["code"], "not_authenticated")

    def test_anonymous_post_create_401_envelope_no_writes(self):
        client = Client()
        user = make_user("alice")
        response = client.post(
            reverse(LOTS),
            {"product_name": "apples", "quantity": "5", "unit": "count"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(error_body(response)["code"], "not_authenticated")
        self.assertEqual(user.household.lots.count(), 0)

    def test_missing_csrf_post_returns_403_envelope_no_writes(self):
        """An authenticated POST with no CSRF token is rejected with the
        csrf_failed envelope and performs zero writes."""
        client = Client(enforce_csrf_checks=True)
        user = make_user("alice")
        login(client, user)
        response = client.post(
            reverse(LOTS),
            {"product_name": "apples", "quantity": "5", "unit": "count"},
        )
        self.assertEqual(response.status_code, 403)
        body = error_body(response)
        self.assertEqual(body["code"], "csrf_failed")
        self.assertEqual(user.household.lots.count(), 0)
        self.assertEqual(user.household.products.count(), 0)
        self.assertEqual(user.household.events.count(), 0)

    def test_missing_csrf_consume_returns_403_envelope_no_writes(self):
        client = Client(enforce_csrf_checks=True)
        user = make_user("alice")
        login(client, user)
        lot = make_lot(user, "apples", "5")
        response = client.post(
            reverse(LOT_CONSUME, args=[lot.pk]), {"quantity": "1"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(error_body(response)["code"], "csrf_failed")
        self.assertEqual(user.household.events.count(), 1)  # only the ADD


class RepresentationTests(TestCase):
    """Exact 3dp strings, UUIDs, ISO timestamps, and derived balance."""

    def setUp(self):
        self.client = Client()
        self.user = make_user("alice")
        login(self.client, self.user)

    def test_create_returns_201_with_envelope_fields(self):
        response = self.client.post(
            reverse(LOTS),
            {
                "product_name": "Apples",
                "quantity": "5.5",
                "unit": "count",
                "location": "fridge",
                "purchased_at": "2026-08-01",
                "expires_on": "2026-08-30",
                "note": "test basket",
            },
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        # Quantity fields are exact 3dp strings.
        self.assertEqual(body["purchase_quantity"], "5.500")
        self.assertEqual(body["balance"], "5.500")
        # UUID and timestamp representations.
        self.assertEqual(len(body["id"]), 36)
        self.assertEqual(body["purchased_at"], "2026-08-01")
        # Timestamps are ISO-8601 UTC (naive "Z" form in DRF default).
        self.assertRegex(body["created_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
        # Nested product summary.
        self.assertEqual(body["product"]["name"], "Apples")
        self.assertEqual(body["product"]["unit"], "count")
        # Location header points at the new lot.
        self.assertEqual(
            response["Location"], f"/api/v1/inventory/lots/{body['id']}/"
        )
        # Expiry in the future bucket.
        self.assertEqual(body["expiry_group"], "later_or_no_date")

    def test_create_normalizes_product_name_via_service(self):
        response = self.client.post(
            reverse(LOTS),
            {"product_name": "  Carrots  ", "quantity": "2", "unit": "count"},
        )
        self.assertEqual(response.status_code, 201)
        # Names are trimmed/collapsed, case preserved.
        self.assertEqual(response.json()["product"]["name"], "Carrots")

    def test_reuse_existing_product_on_second_add(self):
        self.client.post(
            reverse(LOTS),
            {"product_name": "Onions", "quantity": "3", "unit": "count"},
        )
        response = self.client.post(
            reverse(LOTS),
            {"product_name": " onions ", "quantity": "4", "unit": "count"},
        )
        self.assertEqual(response.status_code, 201)
        household = self.user.household
        self.assertEqual(
            household.products.filter(name="Onions").count(), 1
        )
        self.assertEqual(household.lots.count(), 2)

    def test_event_signed_quantity_reflects_ledger_semantics(self):
        lot = make_lot(self.user, "Milk", "2", unit="l")
        services.consume_stock(
            household=self.user.household,
            lot=lot,
            quantity=Decimal("0.5"),
            unit="l",
        )
        services.set_lot_balance(
            household=self.user.household,
            lot=lot,
            observed_balance=Decimal("1.0"),
            note="counted",
        )
        response = self.client.get(reverse(LOT_EVENTS, args=[lot.pk]))
        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        by_type = {e["event_type"]: e for e in results}
        # ADD is positive.
        self.assertEqual(by_type["ADD"]["quantity"], "2.000")
        self.assertEqual(by_type["ADD"]["signed_quantity"], "2.000")
        # CONSUME is negative on the wire, absolute value in quantity.
        self.assertEqual(by_type["CONSUME"]["quantity"], "0.500")
        self.assertEqual(by_type["CONSUME"]["signed_quantity"], "-0.500")
        # ADJUST carries the signed delta (here -0.5).
        self.assertEqual(by_type["ADJUST"]["signed_quantity"], "-0.500")

    def test_validation_envelope_on_bad_create(self):
        response = self.client.post(
            reverse(LOTS),
            {"product_name": "apples", "quantity": "1.0001", "unit": "count"},
        )
        self.assertEqual(response.status_code, 400)
        body = error_body(response)
        self.assertEqual(body["code"], "validation_error")
        self.assertIn("quantity", body["fields"])
        self.assertEqual(self.user.household.lots.count(), 0)

    def test_validation_envelope_on_empty_product_name(self):
        response = self.client.post(
            reverse(LOTS),
            {"product_name": "   ", "quantity": "1", "unit": "count"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(error_body(response)["code"], "validation_error")
        self.assertIn("product_name", error_body(response)["fields"])


class ListTests(TestCase):
    """List endpoint: filtering, pagination, household scoping."""

    def setUp(self):
        self.client = Client()
        self.user = make_user("alice")
        login(self.client, self.user)

    def test_list_returns_paginated_envelope(self):
        make_lot(self.user, "Apples", "5")
        response = self.client.get(reverse(LOTS))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body.keys()), {"count", "next", "previous", "results"})
        self.assertEqual(body["count"], 1)
        self.assertIsNone(body["next"])
        self.assertIsNone(body["previous"])
        self.assertEqual(len(body["results"]), 1)

    def test_list_hides_zero_balance_lots_by_default(self):
        lot = make_lot(self.user, "Apples", "5")
        services.consume_stock(
            household=self.user.household, lot=lot,
            quantity=Decimal("5"), unit="count",
        )
        response = self.client.get(reverse(LOTS))
        self.assertEqual(response.json()["count"], 0)

    def test_list_include_empty_true_shows_zero_balance(self):
        lot = make_lot(self.user, "Apples", "5")
        services.consume_stock(
            household=self.user.household, lot=lot,
            quantity=Decimal("5"), unit="count",
        )
        response = self.client.get(reverse(LOTS) + "?include_empty=true")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)

    def test_list_include_empty_invalid_rejected_400(self):
        response = self.client.get(reverse(LOTS) + "?include_empty=maybe")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(error_body(response)["code"], "validation_error")

    def test_list_include_empty_false(self):
        lot = make_lot(self.user, "Apples", "5")
        services.consume_stock(
            household=self.user.household, lot=lot,
            quantity=Decimal("5"), unit="count",
        )
        response = self.client.get(reverse(LOTS) + "?include_empty=false")
        self.assertEqual(response.json()["count"], 0)

    def test_list_invalid_filter_returns_envelope(self):
        response = self.client.get(reverse(LOTS) + "?location=basement")
        self.assertEqual(response.status_code, 400)
        body = error_body(response)
        self.assertEqual(body["code"], "validation_error")
        self.assertIn("filters", body["fields"])

    def test_list_location_filter(self):
        make_lot(self.user, "Apples", "5", location="fridge")
        make_lot(self.user, "Onions", "5", location="pantry")
        response = self.client.get(reverse(LOTS) + "?location=fridge")
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["product"]["name"], "Apples")

    def test_list_pagination_page_size(self):
        for i in range(3):
            make_lot(self.user, f"Item {i}", "1")
        response = self.client.get(reverse(LOTS) + "?page_size=2&page=1")
        body = response.json()
        self.assertEqual(len(body["results"]), 2)
        self.assertIsNotNone(body["next"])
        response2 = self.client.get(body["next"])
        self.assertEqual(len(response2.json()["results"]), 1)

    def test_list_isolated_from_other_household(self):
        other = make_user("bob")
        make_lot(self.user, "Apples", "5")
        make_lot(other, "Apples", "5")
        response = self.client.get(reverse(LOTS))
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(
            response.json()["results"][0]["product"]["name"], "Apples"
        )


class MutationTests(TestCase):
    """Consume/discard/correct through the API, with CSRF enabled."""

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.user = make_user("alice")
        login(self.client, self.user)

    def _api_post(self, url, payload):
        """POST with a real browser CSRF token: fetch the dashboard page
        (which renders ``{% csrf_token %}`` and sets the csrftoken cookie),
        then send the API POST with the matching ``X-CSRFToken`` header."""
        dashboard = self.client.get(reverse("inventory:dashboard"))
        self.assertEqual(dashboard.status_code, 200)
        token = self.client.cookies["csrftoken"].value
        response = self.client.post(
            url, payload, HTTP_X_CSRFTOKEN=token
        )
        return response

    def test_consume_updates_balance_and_writes_ledger_event(self):
        lot = make_lot(self.user, "Apples", "5")
        response = self._api_post(
            reverse(LOT_CONSUME, args=[lot.pk]), {"quantity": "2", "note": "snack"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["balance"], "3.000")
        self.assertEqual(response.json()["purchase_quantity"], "5.000")
        events = lot.events.order_by("created_at", "id")
        self.assertEqual(events.count(), 2)
        self.assertEqual(events[1].event_type, "CONSUME")
        self.assertEqual(events[1].quantity, Decimal("-2.000"))
        self.assertEqual(events[1].note, "snack")

    def test_discard_reduces_balance(self):
        lot = make_lot(self.user, "Apples", "5")
        response = self._api_post(
            reverse(LOT_DISCARD, args=[lot.pk]), {"quantity": "1"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["balance"], "4.000")

    def test_correct_sets_balance_with_signed_adjust(self):
        lot = make_lot(self.user, "Apples", "5")
        response = self._api_post(
            reverse(LOT_CORRECT, args=[lot.pk]),
            {"observed_balance": "7", "reason": "found more"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["balance"], "7.000")
        adjust = lot.events.filter(event_type="ADJUST").first()
        self.assertEqual(adjust.quantity, Decimal("2.000"))

    def test_correct_no_op_rejected_409(self):
        lot = make_lot(self.user, "Apples", "5")
        response = self._api_post(
            reverse(LOT_CORRECT, args=[lot.pk]),
            {"observed_balance": "5", "reason": "same"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(error_body(response)["code"], "no_op_correction")
        self.assertEqual(lot.events.count(), 1)  # only the ADD

    def test_consume_over_balance_rejected_409_and_rolls_back(self):
        lot = make_lot(self.user, "Apples", "5")
        response = self._api_post(
            reverse(LOT_CONSUME, args=[lot.pk]), {"quantity": "6"}
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(error_body(response)["code"], "insufficient_stock")
        self.assertEqual(lot.events.count(), 1)  # only the ADD, no partial write

    def test_validation_error_envelope_on_mutation(self):
        lot = make_lot(self.user, "Apples", "5")
        response = self._api_post(
            reverse(LOT_CONSUME, args=[lot.pk]), {"quantity": "-1"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(error_body(response)["code"], "validation_error")
        self.assertIn("quantity", error_body(response)["fields"])
        self.assertEqual(lot.events.count(), 1)


class IsolationTests(TestCase):
    """Cross-household requests see indistinguishable 404s, zero writes."""

    def setUp(self):
        self.client = Client()
        self.alice = make_user("alice")
        self.bob = make_user("bob")

    def test_other_household_lot_detail_404(self):
        lot = make_lot(self.alice, "Apples", "5")
        login(self.client, self.bob)
        response = self.client.get(reverse(LOT, args=[lot.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(error_body(response)["code"], "not_found")

    def test_other_household_consume_404_no_writes(self):
        lot = make_lot(self.alice, "Apples", "5")
        login(self.client, self.bob)
        response = self.client.post(
            reverse(LOT_CONSUME, args=[lot.pk]), {"quantity": "1"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(error_body(response)["code"], "not_found")
        self.assertEqual(lot.events.count(), 1)  # Alice's ledger untouched

    def test_unknown_uuid_404(self):
        login(self.client, self.alice)
        response = self.client.get(
            reverse(LOT, args=[uuid.uuid4()])
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(error_body(response)["code"], "not_found")

    def test_unknown_uuid_events_404(self):
        login(self.client, self.alice)
        response = self.client.get(reverse(LOT_EVENTS, args=[uuid.uuid4()]))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(error_body(response)["code"], "not_found")

    def test_bob_cannot_see_alice_lots_in_list(self):
        make_lot(self.alice, "Apples", "5")
        login(self.client, self.bob)
        response = self.client.get(reverse(LOTS))
        self.assertEqual(response.json()["count"], 0)

    def test_other_household_events_404(self):
        lot = make_lot(self.alice, "Apples", "5")
        login(self.client, self.bob)
        response = self.client.get(reverse(LOT_EVENTS, args=[lot.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(error_body(response)["code"], "not_found")

    def test_other_household_discard_404_no_writes(self):
        lot = make_lot(self.alice, "Apples", "5")
        login(self.client, self.bob)
        response = self.client.post(
            reverse(LOT_DISCARD, args=[lot.pk]), {"quantity": "1"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(lot.events.count(), 1)

    def test_other_household_correct_404_no_writes(self):
        lot = make_lot(self.alice, "Apples", "5")
        login(self.client, self.bob)
        response = self.client.post(
            reverse(LOT_CORRECT, args=[lot.pk]),
            {"observed_balance": "1", "reason": "nope"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(lot.events.count(), 1)

    def test_unknown_uuid_consume_404(self):
        login(self.client, self.alice)
        response = self.client.post(
            reverse(LOT_CONSUME, args=[uuid.uuid4()]), {"quantity": "1"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(error_body(response)["code"], "not_found")

    def test_unknown_uuid_discard_404(self):
        login(self.client, self.alice)
        response = self.client.post(
            reverse(LOT_DISCARD, args=[uuid.uuid4()]), {"quantity": "1"}
        )
        self.assertEqual(response.status_code, 404)

    def test_unknown_uuid_correct_404(self):
        login(self.client, self.alice)
        response = self.client.post(
            reverse(LOT_CORRECT, args=[uuid.uuid4()]),
            {"observed_balance": "1", "reason": "nope"},
        )
        self.assertEqual(response.status_code, 404)

    def test_unknown_uuid_not_found_on_list_detail(self):
        login(self.client, self.alice)
        for name in (LOT, LOT_EVENTS):
            response = self.client.get(reverse(name, args=[uuid.uuid4()]))
            self.assertEqual(response.status_code, 404)
            self.assertEqual(error_body(response)["code"], "not_found")


class QuantityInputTests(TestCase):
    """Invalid quantity inputs are rejected with stable 400 envelopes."""

    def setUp(self):
        self.client = Client()
        self.user = make_user("alice")
        login(self.client, self.user)

    def _create(self, quantity):
        return self.client.post(
            reverse(LOTS),
            {"product_name": "Apples", "quantity": quantity, "unit": "count"},
        )

    def test_bool_quantity_rejected(self):
        self.assertEqual(self._create(True).status_code, 400)
        self.assertEqual(self._create(False).status_code, 400)

    def test_nonfinite_quantity_rejected(self):
        self.assertEqual(self._create("Infinity").status_code, 400)
        self.assertEqual(self._create("NaN").status_code, 400)

    def test_imprecise_quantity_rejected(self):
        self.assertEqual(self._create("1.0001").status_code, 400)
        self.assertEqual(self._create("0.1234").status_code, 400)

    def test_consume_nonfinite_rejected(self):
        lot = make_lot(self.user, "Apples", "5")
        response = self.client.post(
            reverse(LOT_CONSUME, args=[lot.pk]), {"quantity": "Infinity"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(error_body(response)["code"], "validation_error")
        self.assertEqual(lot.events.count(), 1)

    def test_zero_quantity_rejected(self):
        self.assertEqual(self._create("0").status_code, 400)
        self.assertEqual(self._create("0.000").status_code, 400)

    def test_negative_create_rejected(self):
        self.assertEqual(self._create("-2").status_code, 400)

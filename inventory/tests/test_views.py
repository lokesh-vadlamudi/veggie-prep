"""Web workflow tests: auth, dashboard grouping, add flow, lot mutations,
CSRF, and cross-household isolation.

All writes go through the views (never the services directly except for
fixture setup), so these tests exercise the full request path including
PRG redirects, error rendering, and household scoping.
"""

from datetime import date, timedelta
from decimal import Decimal
import uuid
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from inventory import services
from inventory.exceptions import (
    InventoryServiceError,
    InvalidQuantity,
    InsufficientStock,
)
from inventory.models import Product, StockLot

User = get_user_model()
PASSWORD = "sup3r-s3cr3t-pass"

DASHBOARD = "inventory:dashboard"
ADD = "inventory:add"
LOGIN = "inventory:login"
LOGOUT = "inventory:logout"


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


def group_names(response, group_key):
    """Product names of the lots in a dashboard expiry group."""
    return [
        item["lot"].product.name
        for item in response.context["groups"][group_key]
    ]


class AuthFlowTests(TestCase):
    """Session login/logout and protected-page redirects."""

    def test_dashboard_requires_auth_with_next(self):
        response = self.client.get(reverse(DASHBOARD))
        self.assertEqual(response.status_code, 302)
        location = response["Location"]
        self.assertTrue(location.startswith(reverse(LOGIN)))
        self.assertEqual(
            parse_qs(urlparse(location).query)["next"], [reverse(DASHBOARD)]
        )

    def test_add_page_requires_auth_with_next(self):
        response = self.client.get(reverse(ADD))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse(LOGIN)))
        self.assertIn("next=", response["Location"])

    def test_lot_detail_requires_auth(self):
        user = make_user("alice")
        lot = make_lot(user, "Onion", "3")
        response = self.client.get(reverse("inventory:lot_detail", args=[lot.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse(LOGIN)))

    def test_post_add_requires_auth(self):
        self.client.post(
            reverse(ADD),
            {"product_name": "Onion", "quantity": "3", "unit": "count"},
        )
        self.assertFalse(Product.objects.exists())

    def test_post_consume_requires_auth(self):
        user = make_user("alice")
        lot = make_lot(user, "Onion", "3")
        before = lot.events.count()
        response = self.client.post(
            reverse("inventory:consume", args=[lot.pk]), {"quantity": "1"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse(LOGIN)))
        self.assertEqual(lot.events.count(), before)

    def test_login_redirects_back_to_requested_page(self):
        user = make_user("alice")
        response = self.client.get(reverse(DASHBOARD))
        location = response["Location"]
        next_value = parse_qs(urlparse(location).query)["next"][0]

        response = self.client.post(
            reverse(LOGIN),
            {"username": "alice", "password": PASSWORD, "next": next_value},
            follow=True,
        )
        self.assertEqual(response.redirect_chain, [(next_value, 302)])
        self.assertContains(response, "Inventory")

    def test_login_bad_credentials_shows_error(self):
        make_user("alice")
        response = self.client.post(
            reverse(LOGIN), {"username": "alice", "password": "wrong"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "Please enter a correct username and password"
        )

    def test_authenticated_user_skips_login(self):
        user = make_user("alice")
        self.client.force_login(user)
        response = self.client.get(reverse(LOGIN))
        self.assertRedirects(response, reverse(DASHBOARD))

    def test_logout_post_returns_to_login_and_kills_session(self):
        user = make_user("alice")
        self.client.force_login(user)
        response = self.client.post(reverse(LOGOUT))
        self.assertRedirects(response, reverse(LOGIN))
        response = self.client.get(reverse(DASHBOARD))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse(LOGIN)))


class AddFlowTests(TestCase):
    """Add flow: validation, product normalization/reuse, PRG, error display."""

    def setUp(self):
        self.user = make_user("alice")
        self.client.force_login(self.user)

    def post_add(self, follow=False, **overrides):
        payload = {
            "product_name": "Onion",
            "quantity": "3",
            "unit": "count",
            "location": "pantry",
            "purchased_at": "",
            "expires_on": "",
            "note": "",
        }
        payload.update(overrides)
        return self.client.post(reverse(ADD), payload, follow=follow)

    def test_add_onion_prg_and_persist(self):
        response = self.post_add(follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain, [(reverse(DASHBOARD), 302)])

        product = Product.objects.get(household=self.user.household)
        self.assertEqual(product.name, "Onion")
        self.assertEqual(product.unit, "count")
        lot = product.lots.get()
        self.assertEqual(services.lot_balance(lot), Decimal("3.000"))
        self.assertEqual(lot.location, "pantry")
        self.assertIsNone(lot.purchased_at)
        self.assertIsNone(lot.expires_on)
        event = lot.events.get()
        self.assertEqual(event.event_type, "ADD")
        self.assertEqual(event.quantity, Decimal("3.000"))

        # PRG: the redirect target is a plain GET page carrying the message.
        self.assertContains(response, "Added 3 count Onion to pantry.")

    def test_add_tomato_with_dates_and_note(self):
        response = self.post_add(
            product_name="Tomato",
            quantity="500",
            unit="g",
            location="fridge",
            purchased_at="2026-08-01",
            expires_on="2026-08-30",
            note="local farm",
        )
        self.assertRedirects(response, reverse(DASHBOARD))
        lot = Product.objects.get(
            household=self.user.household, name="Tomato"
        ).lots.get()
        self.assertEqual(lot.purchased_at, date(2026, 8, 1))
        self.assertEqual(lot.expires_on, date(2026, 8, 30))
        self.assertEqual(lot.location, "fridge")
        self.assertEqual(lot.events.get().note, "local farm")

    def test_normalized_product_reuse(self):
        self.post_add(product_name="  toMaTo   ", quantity="1", unit="each")
        self.post_add(product_name="TOMATO", quantity="2", unit="each")

        products = list(Product.objects.filter(household=self.user.household))
        self.assertEqual(len(products), 1)
        # The first spelling is stored; later matches reuse it case-insensitively.
        self.assertEqual(products[0].name, "toMaTo")
        self.assertEqual(products[0].unit, "each")

        lots = list(products[0].lots.order_by("id"))
        self.assertEqual(len(lots), 2)
        self.assertEqual(
            sum(services.lot_balance(lot) for lot in lots), Decimal("3.000")
        )

    def test_whitespace_normalization_on_reuse(self):
        self.post_add(product_name="Garlic", quantity="2", unit="count")
        response = self.post_add(
            product_name="  \t gArLiC \n ", quantity="1", unit="count"
        )
        self.assertRedirects(response, reverse(DASHBOARD))
        self.assertEqual(
            Product.objects.filter(household=self.user.household).count(), 1
        )
        product = Product.objects.get(household=self.user.household)
        self.assertEqual(product.name, "Garlic")

    def test_unit_conflict_rejected_no_partial_write(self):
        make_lot(self.user, "Flour", "100", unit="g")
        response = self.post_add(product_name="flour", quantity="50", unit="ml")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")
        self.assertContains(response, "ml")
        self.assertEqual(
            Product.objects.filter(household=self.user.household).count(), 1
        )
        self.assertEqual(StockLot.objects.count(), 1)
        self.assertEqual(
            Product.objects.get(household=self.user.household, name="Flour")
            .lots.get()
            .events.count(),
            1,
        )

    def test_zero_quantity_rejected(self):
        response = self.post_add(quantity="0")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Quantity")
        self.assertFalse(StockLot.objects.exists())

    def test_negative_quantity_rejected(self):
        response = self.post_add(quantity="-1")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Quantity")
        self.assertFalse(StockLot.objects.exists())

    def test_imprecise_quantity_rejected(self):
        response = self.post_add(quantity="0.1234")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "3 decimal places")
        self.assertFalse(StockLot.objects.exists())
        self.assertFalse(Product.objects.exists())

    def test_non_numeric_quantity_rejected(self):
        response = self.post_add(quantity="abc")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Quantity")
        self.assertFalse(StockLot.objects.exists())

    def test_missing_product_name_rejected(self):
        response = self.post_add(product_name="")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Product")
        self.assertFalse(Product.objects.exists())

    def test_invalid_unit_choice_rejected(self):
        response = self.post_add(unit="stone")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.exists())

    def test_invalid_location_choice_rejected(self):
        response = self.post_add(location="basement")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(StockLot.objects.exists())

    def test_add_page_renders(self):
        response = self.client.get(reverse(ADD))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add stock")
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_add_rolls_back_created_product_when_service_fails(self):
        """Product resolution succeeds but the lot write fails: the whole
        add transaction rolls back, no partial product/lot rows remain, and
        the failure is shown to the user."""
        with mock.patch.object(
            services, "add_stock", side_effect=InventoryServiceError("boom")
        ):
            response = self.post_add(product_name="Zucchini")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "boom")
        self.assertEqual(
            Product.objects.filter(
                household=self.user.household, name__iexact="zucchini"
            ).count(),
            0,
        )
        self.assertEqual(self.user.household.lots.count(), 0)


class LotDetailTests(TestCase):
    """Lot detail: balance, metadata, no-expiry label, audit history."""

    def setUp(self):
        self.user = make_user("alice")
        self.client.force_login(self.user)

    def detail(self, lot):
        return self.client.get(reverse("inventory:lot_detail", args=[lot.pk]))

    def test_detail_shows_balance_and_metadata(self):
        lot = make_lot(
            self.user,
            "Onion",
            "3",
            location="fridge",
            purchased_at=date(2026, 8, 1),
            expires_on=date(2026, 8, 20),
        )
        response = self.detail(lot)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Onion")
        self.assertContains(response, "3.000 <span class=\"unit\">count</span>")
        self.assertContains(response, "fridge")
        self.assertContains(response, "2026-08-01")
        self.assertContains(response, "2026-08-20")

    def test_detail_no_expiry_label(self):
        lot = make_lot(self.user, "Salt", "1", unit="g")
        self.assertContains(self.detail(lot), "No expiry date")

    def test_detail_zero_balance_lot_still_visible(self):
        lot = make_lot(self.user, "Onion", "1")
        services.consume_stock(
            household=self.user.household,
            lot=lot,
            quantity=Decimal("1"),
            unit="count",
        )
        response = self.detail(lot)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "0.000 <span class=\"unit\">count</span>"
        )

    def test_history_chronological_with_all_event_types(self):
        lot = make_lot(self.user, "Cabbage", "5", unit="g")
        services.consume_stock(
            household=self.user.household,
            lot=lot,
            quantity=Decimal("1"),
            unit="g",
            note="lunch",
        )
        services.discard_stock(
            household=self.user.household,
            lot=lot,
            quantity=Decimal("1"),
            unit="g",
            note="spoiled",
        )
        services.adjust_stock(
            household=self.user.household,
            lot=lot,
            delta=Decimal("-1"),
            unit="g",
            note="miscount",
        )
        response = self.detail(lot)
        events = [
            (event.event_type, event.quantity)
            for event in response.context["events"]
        ]
        self.assertEqual(
            events,
            [
                ("ADD", Decimal("5.000")),
                ("CONSUME", Decimal("-1.000")),
                ("DISCARD", Decimal("-1.000")),
                ("ADJUST", Decimal("-1.000")),
            ],
        )
        self.assertContains(response, "lunch")
        self.assertContains(response, "spoiled")
        self.assertContains(response, "miscount")
        self.assertContains(response, "add")
        self.assertContains(response, "consume")
        self.assertContains(response, "discard")
        self.assertContains(response, "adjust")

    def test_history_empty_state(self):
        product = Product.objects.create(
            household=self.user.household, name="Kale", unit="g"
        )
        lot = StockLot.objects.create(
            household=self.user.household,
            product=product,
            quantity=Decimal("2"),
            unit="g",
        )
        response = self.detail(lot)
        self.assertContains(response, "No events recorded for this lot yet.")


class MutationTests(TestCase):
    """Consume / discard / correct: PRG on success, errors on failure."""

    def setUp(self):
        self.user = make_user("alice")
        self.client.force_login(self.user)
        self.lot = make_lot(self.user, "Onion", "5", unit="g")

    def consume(self, follow=False, **overrides):
        payload = {"quantity": "1.5", "note": ""}
        payload.update(overrides)
        return self.client.post(
            reverse("inventory:consume", args=[self.lot.pk]),
            payload,
            follow=follow,
        )

    def discard(self, follow=False, **overrides):
        payload = {"quantity": "1", "note": ""}
        payload.update(overrides)
        return self.client.post(
            reverse("inventory:discard", args=[self.lot.pk]),
            payload,
            follow=follow,
        )

    def correct(self, follow=False, **overrides):
        payload = {"observed_balance": "1", "reason": ""}
        payload.update(overrides)
        return self.client.post(
            reverse("inventory:correct", args=[self.lot.pk]),
            payload,
            follow=follow,
        )

    def detail_url(self):
        return reverse("inventory:lot_detail", args=[self.lot.pk])

    def balance(self):
        return services.lot_balance(self.lot)

    def test_consume_success_prg(self):
        response = self.consume(follow=True, note="lunch")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain, [(self.detail_url(), 302)])
        self.assertContains(response, "Consumed 1.5 g Onion.")
        self.assertEqual(self.balance(), Decimal("3.500"))
        event = self.lot.events.get(event_type="CONSUME")
        self.assertEqual(event.quantity, Decimal("-1.500"))
        self.assertEqual(event.note, "lunch")

    def test_discard_success_prg(self):
        response = self.discard(follow=True, note="spoiled")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain, [(self.detail_url(), 302)])
        self.assertContains(response, "Discarded 1 g Onion.")
        self.assertEqual(self.balance(), Decimal("4.000"))
        self.assertEqual(
            self.lot.events.get(event_type="DISCARD").quantity,
            Decimal("-1.000"),
        )

    def test_consume_over_balance_shows_error_no_write(self):
        events_before = self.lot.events.count()
        response = self.consume(quantity="999")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "lot balance is")
        self.assertEqual(self.balance(), Decimal("5.000"))
        self.assertEqual(self.lot.events.count(), events_before)

    def test_consume_zero_rejected(self):
        response = self.consume(quantity="0")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Quantity")
        self.assertEqual(self.lot.events.count(), 1)

    def test_consume_imprecise_rejected(self):
        response = self.consume(quantity="0.1234")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "3 decimal places")
        self.assertEqual(self.lot.events.count(), 1)

    def test_correct_increase_applies_positive_delta(self):
        response = self.correct(
            follow=True, observed_balance="6.5", reason="counted more"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain, [(self.detail_url(), 302)])
        self.assertContains(response, "Corrected Onion to 6.5 g.")
        self.assertEqual(self.balance(), Decimal("6.500"))
        event = self.lot.events.get(event_type="ADJUST")
        self.assertEqual(event.quantity, Decimal("1.500"))
        self.assertEqual(event.note, "counted more")

    def test_correct_decrease_applies_negative_delta(self):
        response = self.correct(
            follow=True, observed_balance="0.25", reason="ate some"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain, [(self.detail_url(), 302)])
        self.assertEqual(self.balance(), Decimal("0.250"))
        self.assertEqual(
            self.lot.events.get(event_type="ADJUST").quantity,
            Decimal("-4.750"),
        )

    def test_correct_noop_rejected_no_event(self):
        events_before = self.lot.events.count()
        response = self.correct(observed_balance="5", reason="thought I miscounted")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No-op")
        self.assertEqual(self.lot.events.count(), events_before)

    def test_correct_requires_reason(self):
        response = self.correct(observed_balance="4", reason="")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reason")
        self.assertContains(response, "This field is required.")
        self.assertEqual(self.lot.events.count(), 1)

    def test_correct_imprecise_observed_rejected(self):
        response = self.correct(observed_balance="5.0005", reason="off")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "3 decimal places")
        self.assertEqual(self.lot.events.count(), 1)

    def test_correct_negative_observed_rejected(self):
        response = self.correct(observed_balance="-1", reason="off")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Observed balance")
        self.assertEqual(self.lot.events.count(), 1)

    def test_failed_post_renders_detail_without_partial_write(self):
        events_before = self.lot.events.count()
        response = self.consume(quantity="9999")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.lot.events.count(), events_before)
        # The re-rendered page still shows the lot and the action forms.
        self.assertContains(
            response,
            reverse("inventory:lot_detail", args=[self.lot.pk]),
            status_code=200,
        )
        self.assertContains(response, "Adjust this lot")

    def test_get_mutation_url_redirects_to_detail(self):
        response = self.client.get(
            reverse("inventory:consume", args=[self.lot.pk])
        )
        self.assertRedirects(
            response, reverse("inventory:lot_detail", args=[self.lot.pk])
        )

    def test_consume_quantity_error_maps_to_quantity_field(self):
        """Service-level quantity errors render on the consume/discard
        quantity field, not as non-field errors."""
        from inventory.views import ConsumeView

        view = ConsumeView()
        self.assertEqual(
            view.field_for_exception(InvalidQuantity("bad")), "quantity"
        )
        self.assertIsNone(
            view.field_for_exception(InsufficientStock("over balance"))
        )

    def test_correct_value_error_maps_to_observed_balance_field(self):
        """Correction value errors render on the observed_balance field;
        adjustment errors (e.g. no-op) stay non-field."""
        from inventory.views import CorrectView

        view = CorrectView()
        self.assertEqual(
            view.field_for_exception(InvalidQuantity("bad")),
            "observed_balance",
        )
        self.assertIsNone(view.field_for_exception(InsufficientStock("x")))


class DashboardExpiryTests(TestCase):
    """Dashboard: positive-balance lots grouped by expiry boundary, no-expiry
    label, zero-balance hiding, empty state."""

    TODAY = date(2026, 8, 17)

    def setUp(self):
        self.user = make_user("alice")
        self.client.force_login(self.user)
        self.patcher = mock.patch(
            "django.utils.timezone.localdate", return_value=self.TODAY
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def dashboard(self):
        return self.client.get(reverse(DASHBOARD))

    def test_expiry_boundary_groups(self):
        make_lot(self.user, "Almond", "1", expires_on=self.TODAY - timedelta(days=7))
        make_lot(self.user, "Banana", "1", expires_on=self.TODAY)
        make_lot(self.user, "Carrot", "1", expires_on=self.TODAY + timedelta(days=1))
        make_lot(self.user, "Daikon", "1", expires_on=self.TODAY + timedelta(days=2))
        make_lot(self.user, "Eggplant", "1", expires_on=self.TODAY + timedelta(days=3))
        make_lot(self.user, "Garlic", "1")

        response = self.dashboard()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(group_names(response, "expired"), ["Almond"])
        self.assertEqual(group_names(response, "today"), ["Banana"])
        self.assertEqual(group_names(response, "next2"), ["Carrot", "Daikon"])
        self.assertEqual(group_names(response, "later"), ["Eggplant", "Garlic"])

    def test_missing_expiry_label(self):
        make_lot(self.user, "Garlic", "1")
        self.assertContains(self.dashboard(), "No expiry date")

    def test_zero_balance_lot_hidden_from_dashboard(self):
        visible = make_lot(self.user, "Visible", "1")
        hidden = make_lot(self.user, "Hidden", "1")
        services.consume_stock(
            household=self.user.household,
            lot=hidden,
            quantity=Decimal("1"),
            unit="count",
        )
        response = self.dashboard()
        self.assertContains(response, "Visible")
        self.assertNotContains(response, "Hidden")
        self.assertEqual(response.context["total_lots"], 1)
        for items in response.context["groups"].values():
            for item in items:
                self.assertNotEqual(item["lot"], hidden)
                self.assertGreater(item["balance"], 0)

    def test_expired_today_next2_later_headings(self):
        make_lot(self.user, "Almond", "1", expires_on=self.TODAY - timedelta(days=1))
        response = self.dashboard()
        self.assertContains(response, "Expired")
        self.assertContains(response, "Today")
        self.assertContains(response, "Next 2 days")
        self.assertContains(response, "Later / no date")
        self.assertContains(response, 'id="group-expired"')
        self.assertContains(response, 'id="group-today"')
        self.assertContains(response, 'id="group-next2"')
        self.assertContains(response, 'id="group-later"')

    def test_empty_dashboard_state(self):
        response = self.dashboard()
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "No stock lots with a positive balance yet"
        )
        self.assertContains(response, "Fast add")
        self.assertEqual(response.context["total_lots"], 0)


class CrossHouseholdIsolationTests(TestCase):
    """Household B must 404 (never 403/500/leak) on Household A's lot IDs."""

    def setUp(self):
        self.user_a = make_user("alice")
        self.user_b = make_user("bob")
        self.client_a = Client()
        self.client_b = Client()
        login(self.client_a, self.user_a)
        login(self.client_b, self.user_b)
        self.lot_a = make_lot(self.user_a, "Onion", "3")

    def test_b_get_a_lot_detail_404(self):
        response = self.client_b.get(
            reverse("inventory:lot_detail", args=[self.lot_a.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_b_post_consume_a_lot_404(self):
        response = self.client_b.post(
            reverse("inventory:consume", args=[self.lot_a.pk]),
            {"quantity": "1"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.lot_a.events.count(), 1)

    def test_b_post_discard_a_lot_404(self):
        response = self.client_b.post(
            reverse("inventory:discard", args=[self.lot_a.pk]),
            {"quantity": "1"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.lot_a.events.count(), 1)

    def test_b_post_correct_a_lot_404(self):
        response = self.client_b.post(
            reverse("inventory:correct", args=[self.lot_a.pk]),
            {"observed_balance": "1", "reason": "phishing"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.lot_a.events.count(), 1)

    def test_b_get_a_lot_mutation_urls_404(self):
        for url in ("consume", "discard", "correct"):
            response = self.client_b.get(
                reverse(f"inventory:{url}", args=[self.lot_a.pk])
            )
            self.assertEqual(response.status_code, 404, url)

    def test_b_dashboard_does_not_list_a_products(self):
        response = self.client_b.get(reverse(DASHBOARD))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Onion")

    def test_unknown_lot_pk_404_for_owner(self):
        response = self.client_a.get(
            reverse("inventory:lot_detail", args=[uuid.uuid4()])
        )
        self.assertEqual(response.status_code, 404)
        response = self.client_a.post(
            reverse("inventory:consume", args=[uuid.uuid4()]), {"quantity": "1"}
        )
        self.assertEqual(response.status_code, 404)

    def test_a_products_unaffected_after_b_attempts(self):
        for payload, url in (
            ({"quantity": "1"}, "inventory:consume"),
            ({"quantity": "1"}, "inventory:discard"),
            ({"observed_balance": "1", "reason": "x"}, "inventory:correct"),
        ):
            self.client_b.post(reverse(url, args=[self.lot_a.pk]), payload)
        self.assertEqual(self.lot_a.events.count(), 1)
        self.assertEqual(services.lot_balance(self.lot_a), Decimal("3.000"))
        self.assertEqual(
            Product.objects.filter(household=self.user_b.household).count(), 0
        )


class CsrfAndTemplateTests(TestCase):
    """CSRF tokens in every form-bearing template; POSTs without token
    are rejected without side effects."""

    def setUp(self):
        self.user = make_user("alice")
        self.client.force_login(self.user)
        self.lot = make_lot(self.user, "Onion", "3")

    def test_csrf_token_in_all_form_pages(self):
        pages = [
            self.client.get(reverse(DASHBOARD)),
            self.client.get(reverse(ADD)),
        ]
        self.client.logout()
        pages.append(self.client.get(reverse(LOGIN)))
        for page in pages:
            self.assertEqual(page.status_code, 200)
            self.assertContains(page, "csrfmiddlewaretoken")

    def test_lot_detail_csrf_token_inside_each_action_form(self):
        """Per-form assertion: one {% csrf_token %} inside each of the
        consume / discard / correct <form> blocks. A whole-page substring
        check is a false positive — it passes if any form on the page has a
        token even when sibling forms are missing it."""
        response = self.client.get(
            reverse("inventory:lot_detail", args=[self.lot.pk])
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        for action, marker in (
            ("consume", "name=\"quantity\""),
            ("discard", "name=\"quantity\""),
            ("correct", "name=\"observed_balance\""),
        ):
            start = content.index(f"action=\"{reverse(f'inventory:{action}', args=[self.lot.pk])}\"")
            end = content.index("</form>", start)
            form_block = content[start:end]
            self.assertIn(
                "csrfmiddlewaretoken",
                form_block,
                f"consume/discard/correct form for {action!r} is missing a "
                "csrf_token inside its own <form> block",
            )

    def test_get_token_then_post_succeeds_enforced_csrf(self):
        """Regression: a token read from the rendered lot_detail page must be
        accepted by an enforced-CSRF client on all three action endpoints
        (proving the per-form tokens are the ones the POSTs read)."""
        strict = Client(enforce_csrf_checks=True)
        login(strict, self.user)
        page = strict.get(reverse("inventory:lot_detail", args=[self.lot.pk]))
        self.assertEqual(page.status_code, 200)
        content = page.content.decode("utf-8")
        import re

        def token_for(action):
            start = content.index(
                f"action=\"{reverse(f'inventory:{action}', args=[self.lot.pk])}\""
            )
            end = content.index("</form>", start)
            match = re.search(
                r'name="csrfmiddlewaretoken" value="([^"]+)"', content[start:end]
            )
            self.assertIsNotNone(match, f"no token inside {action} form")
            return match.group(1)

        events_before = self.lot.events.count()
        response = strict.post(
            reverse("inventory:consume", args=[self.lot.pk]),
            {"quantity": "1", "csrfmiddlewaretoken": token_for("consume")},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.lot.events.count(), events_before + 1)
        self.assertEqual(services.lot_balance(self.lot), Decimal("2.000"))

        response = strict.post(
            reverse("inventory:discard", args=[self.lot.pk]),
            {"quantity": "1", "csrfmiddlewaretoken": token_for("discard")},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.lot.events.count(), events_before + 2)
        self.assertEqual(services.lot_balance(self.lot), Decimal("1.000"))

        response = strict.post(
            reverse("inventory:correct", args=[self.lot.pk]),
            {
                "observed_balance": "4",
                "reason": "recounted",
                "csrfmiddlewaretoken": token_for("correct"),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.lot.events.count(), events_before + 3)
        self.assertEqual(services.lot_balance(self.lot), Decimal("4.000"))

    def test_post_without_csrf_rejected_add(self):
        strict = Client(enforce_csrf_checks=True)
        login(strict, self.user)
        response = strict.post(
            reverse(ADD),
            {"product_name": "Onion", "quantity": "3", "unit": "count"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            Product.objects.filter(household=self.user.household, name="Onion").count(),
            1,  # only the fixture lot's product
        )
        self.assertEqual(StockLot.objects.count(), 1)

    def test_post_without_csrf_rejected_consume(self):
        strict = Client(enforce_csrf_checks=True)
        login(strict, self.user)
        events_before = self.lot.events.count()
        response = strict.post(
            reverse("inventory:consume", args=[self.lot.pk]), {"quantity": "1"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.lot.events.count(), events_before)

    def test_login_page_contains_csrf_and_next_field(self):
        self.client.logout()
        response = self.client.get(
            reverse(LOGIN), {"next": reverse(DASHBOARD)}
        )
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertContains(response, 'name="next"')

    def test_dashboard_links_css(self):
        response = self.client.get(reverse(DASHBOARD))
        self.assertContains(response, "styles.css")

    def test_narrow_status_pills_do_not_split_mid_word(self):
        # Regression: at 390px the suggested status pill in meal history split
        # mid-word because table cells use overflow-wrap: anywhere. The pills
        # must opt out with white-space: nowrap.
        from pathlib import Path

        css = (
            Path(__file__).resolve().parents[1]
            / "static"
            / "inventory"
            / "styles.css"
        ).read_text(encoding="utf-8")
        for selector in (".status {", ".rescued-badge {"):
            rule = css.split(selector, 1)[1].split("}", 1)[0]
            self.assertIn(
                "white-space: nowrap;",
                rule,
                f"{selector!r} rule must set white-space: nowrap so the "
                "pill does not wrap mid-word at narrow (390px) widths",
            )


class NormalizeProductNameTests(TestCase):
    def test_trim_and_collapse(self):
        from inventory.views import normalize_product_name

        self.assertEqual(normalize_product_name("  ToMaTo "), "ToMaTo")
        self.assertEqual(
            normalize_product_name(" \t\n  green   bean \n "),
            "green bean",
        )
        self.assertEqual(normalize_product_name(""), "")

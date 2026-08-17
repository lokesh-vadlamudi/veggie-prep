"""Meal API tests: list/detail/generate/cook boundaries.

Covers auth/CSRF, household isolation, pagination/status filtering, safe
allocation output, exact 3dp quantities, fake-provider success and every
provider failure class (zero writes), exactly-once service calls, and
cook duplicate/conflict/rollback semantics. All provider interaction goes
through the fake provider stand-in; no network is touched.
"""

import json
import uuid
from datetime import timedelta, timezone as _dt_timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from inventory import meal_services, services
from inventory.ai.exceptions import (
    AIConfigError,
    AIMalformedOutputError,
    AIOutputTooLargeError,
    AIProviderError,
    AIRequestError,
)
from inventory.models import InventoryEvent, MealEvent, MealIngredient, MealSuggestion
from inventory.tests.test_api import (
    error_body,
    login,
    make_lot,
    make_user,
)
from inventory.tests.test_meals import FakeProvider, valid_payload

User = get_user_model()

MEALS = "api:meals_list"
MEAL = "api:meal_detail"
MEAL_GENERATE = "api:meal_generate"
MEAL_COOK = "api:meal_cook"


def api_timestamp(value):
    """The one deterministic API timestamp format: ISO-8601 UTC with a
    ``Z`` suffix, mirroring ``serializers.api_timestamp``."""
    text = value.astimezone(_dt_timezone.utc).isoformat()
    if text.endswith("+00:00"):
        text = text[:-6] + "Z"
    return text


def get_meal_detail(client, suggestion):
    """GET a meal detail, asserting the shape of the success path."""
    response = client.get(reverse(MEAL, args=[suggestion.pk]))
    assert response.status_code == 200, response.status_code
    return response.json()


def make_suggestion(
    user,
    status=MealSuggestion.Status.SUGGESTED,
    title="Garlicky onion stir-fry",
    servings=2,
    time_minutes=25,
    with_event=False,
):
    """Create a suggestion + matching ingredient rows directly (fixture)."""
    suggestion = MealSuggestion.objects.create(
        household=user.household,
        status=status,
        title=title,
        servings=servings,
        time_minutes=time_minutes,
        steps=["Chop.", "Stir-fry."],
        substitutions=["Oil for butter."],
        safety_note="Hot pan.",
        rationale="Onions expire soon.",
        provider_model="fake-model",
    )
    if with_event:
        MealEvent.objects.create(household=user.household, suggestion=suggestion)
    return suggestion


class MealListTests(TestCase):
    """GET /api/v1/meals/ — auth, ordering, pagination, status filter."""

    def setUp(self):
        self.user = make_user("meal-list-user")
        self.client = Client()
        login(self.client, self.user)
        self.other = make_user("meal-list-other")

    def _two_suggestions(self):
        a = make_suggestion(self.user, title="Meal A")
        b = make_suggestion(self.user, title="Meal B")
        return a, b

    def test_anonymous_returns_envelope(self):
        client = Client()
        response = client.get(reverse(MEALS))
        assert response.status_code == 403, response.content
        assert error_body(response)["code"] == "not_authenticated"

    def test_authenticated_empty_list(self):
        response = self.client.get(reverse(MEALS))
        assert response.status_code == 200
        body = response.json()
        assert body["results"] == []
        assert body["count"] == 0

    def test_household_scoping_and_newest_first(self):
        from django.utils import timezone

        foreign = make_suggestion(self.other, title="Foreign Meal")
        a, b = self._two_suggestions()
        # Force strictly distinct timestamps so ordering never depends on
        # same-microsecond ties.
        MealSuggestion.objects.filter(pk=a.pk).update(
            created_at=timezone.now() - timedelta(days=2)
        )
        MealSuggestion.objects.filter(pk=b.pk).update(
            created_at=timezone.now() - timedelta(days=1)
        )
        response = self.client.get(reverse(MEALS))
        assert response.status_code == 200
        body = response.json()
        titles = [row["title"] for row in body["results"]]
        assert titles == ["Meal B", "Meal A"]
        assert foreign.title not in titles
        assert body["count"] == 2

    def test_summary_fields_and_exact_strings(self):
        # Newest-first ordering puts Meal B (created last) in results[0];
        # assert against the returned object, not the other fixture.
        _, suggestion = self._two_suggestions()
        suggestion.refresh_from_db()
        created = api_timestamp(suggestion.created_at)
        response = self.client.get(reverse(MEALS))
        row = response.json()["results"][0]
        assert row["id"] == str(suggestion.pk)
        assert row["title"] == "Meal B"
        assert row["status"] == "suggested"
        assert row["servings"] == 2
        assert row["time_minutes"] == 25
        assert row["created_at"] == created
        assert row["cooked_at"] is None
        assert row["missing_ingredient_count"] == 0
        assert row["rescued_ingredient_count"] == 0

    def test_status_filter_exact_match(self):
        suggested = make_suggestion(self.user, title="S1")
        cooked = make_suggestion(
            self.user, status=MealSuggestion.Status.COOKED, title="C1"
        )
        rejected = make_suggestion(
            self.user, status=MealSuggestion.Status.REJECTED, title="R1"
        )
        for value, expected in (
            ("suggested", [suggested.pk]),
            ("cooked", [cooked.pk]),
            ("rejected", [rejected.pk]),
        ):
            response = self.client.get(
                reverse(MEALS), {"status": value}
            )
            assert response.status_code == 200
            ids = [row["id"] for row in response.json()["results"]]
            assert ids == [str(expected[0])], (value, ids)

    def test_status_filter_invalid_rejected_with_no_writes(self):
        before = self.user.household.meal_suggestions.count()
        response = self.client.get(reverse(MEALS), {"status": "done"})
        assert response.status_code == 400
        assert error_body(response)["code"] == "validation_error"
        assert (
            self.user.household.meal_suggestions.count() == before
        )

    def test_pagination_defaults_and_bounds(self):
        for i in range(150):
            make_suggestion(self.user, title=f"Meal {i:03d}")
        response = self.client.get(reverse(MEALS))
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 150
        assert len(body["results"]) == 50  # default page size

    def test_pagination_page_size_clamped_to_max(self):
        for i in range(150):
            make_suggestion(self.user, title=f"Meal {i:03d}")
        response = self.client.get(
            reverse(MEALS), {"page_size": "500", "page": "2"}
        )
        assert response.status_code == 200, response.content
        body = response.json()
        # 150 rows with page size clamped to the max of 100:
        # page 1 holds 100, so page 2 holds the remaining 50.
        assert len(body["results"]) == 50

    def test_missing_cooked_at_rendered_null(self):
        make_suggestion(self.user, title="No event")
        response = self.client.get(reverse(MEALS))
        row = response.json()["results"][0]
        assert row["cooked_at"] is None


class MealDetailTests(TestCase):
    """GET /api/v1/meals/<uuid>/ — safe detail with ordered, household-only
    allocation fields and exact 3dp quantities."""

    def setUp(self):
        self.user = make_user("meal-detail-user")
        self.client = Client()
        login(self.client, self.user)
        self.other = make_user("meal-detail-other")

    def _suggestion_with_allocations(self, owner):
        suggestion = make_suggestion(owner, title="Detail Meal")
        lot_a = make_lot(owner, "Onion", "4.500", unit="count")
        lot_b = make_lot(owner, "Onion", "2.000", unit="count")
        MealIngredient.objects.create(
            suggestion=suggestion,
            household=owner.household,
            name="Onion",
            unit="count",
            required_quantity=Decimal("6.500"),
            owned_quantity=Decimal("6.500"),
            missing_quantity=Decimal("0.000"),
            # Consistent with service semantics: the ingredient-level flag
            # is the OR-fold across its allocations (one is rescued).
            rescued=True,
            allocations=[
                {"lot": str(lot_a.pk), "quantity": "4.5", "rescued": False},
                {"lot": str(lot_b.pk), "quantity": "2", "rescued": True},
            ],
        )
        MealIngredient.objects.create(
            suggestion=suggestion,
            household=owner.household,
            name="garlic",
            unit="g",
            required_quantity=Decimal("10.000"),
            owned_quantity=Decimal("0.000"),
            missing_quantity=Decimal("10.000"),
            rescued=False,
            allocations=[],
        )
        return suggestion, lot_a, lot_b

    def test_anonymous_returns_envelope(self):
        suggestion, *_ = self._suggestion_with_allocations(self.user)
        client = Client()
        response = client.get(reverse(MEAL, args=[suggestion.pk]))
        assert response.status_code == 403
        assert error_body(response)["code"] == "not_authenticated"

    def test_full_detail_representation(self):
        suggestion, lot_a, lot_b = self._suggestion_with_allocations(self.user)
        body = get_meal_detail(self.client, suggestion)
        assert body["id"] == str(suggestion.pk)
        assert body["status"] == "suggested"
        assert body["title"] == "Detail Meal"
        assert body["servings"] == 2
        assert body["time_minutes"] == 25
        assert body["steps"] == ["Chop.", "Stir-fry."]
        assert body["substitutions"] == ["Oil for butter."]
        assert body["safety_note"] == "Hot pan."
        assert body["rationale"] == "Onions expire soon."
        assert body["provider_model"] == "fake-model"
        assert body["cooked_at"] is None
        assert len(body["ingredients"]) == 2
        onion = body["ingredients"][0]
        assert onion["name"] == "Onion"
        assert onion["unit"] == "count"
        assert onion["required_quantity"] == "6.500"
        assert onion["owned_quantity"] == "6.500"
        assert onion["missing_quantity"] == "0.000"
        assert onion["rescued"] is True
        assert len(onion["allocations"]) == 2
        # ``rescued`` mirrors each allocation's per-lot flag; the
        # ingredient-level flag is OR-folded across its allocations.
        first = onion["allocations"][0]
        assert first["lot_id"] == str(lot_a.pk)
        assert first["quantity"] == "4.500"
        assert first["unit"] == "count"
        assert first["rescued"] is False
        assert first["expires_on"] is None
        second = onion["allocations"][1]
        assert second["lot_id"] == str(lot_b.pk)
        assert second["quantity"] == "2.000"
        assert second["rescued"] is True
        garlic = body["ingredients"][1]
        assert garlic["name"] == "garlic"
        assert garlic["required_quantity"] == "10.000"
        assert garlic["missing_quantity"] == "10.000"
        assert garlic["allocations"] == []

    def test_cooked_at_populated_from_meal_event(self):
        suggestion, *_ = self._suggestion_with_allocations(self.user)
        MealEvent.objects.create(
            household=self.user.household, suggestion=suggestion
        )
        body = get_meal_detail(self.client, suggestion)
        event = suggestion.meal_event
        assert body["cooked_at"] == api_timestamp(event.cooked_at)

    def test_foreign_suggestion_is_404(self):
        foreign, *_ = self._suggestion_with_allocations(self.other)
        response = self.client.get(reverse(MEAL, args=[foreign.pk]))
        assert response.status_code == 404
        assert error_body(response)["code"] == "not_found"

    def test_unknown_uuid_is_404(self):
        response = self.client.get(
            reverse(MEAL, args=[uuid.uuid4()])
        )
        assert response.status_code == 404
        assert error_body(response)["code"] == "not_found"

    def test_allocation_for_foreign_lot_is_never_exposed(self):

        suggestion = make_suggestion(self.user, title="Leak Check")
        foreign_lot = make_lot(self.other, "Onion", "3.000", unit="count")
        own_lot = make_lot(self.user, "Onion", "1.000", unit="count")
        MealIngredient.objects.create(
            suggestion=suggestion,
            household=self.user.household,
            name="Onion",
            unit="count",
            required_quantity=Decimal("4.000"),
            owned_quantity=Decimal("1.000"),
            missing_quantity=Decimal("3.000"),
            rescued=False,
            allocations=[
                {"lot": str(own_lot.pk), "quantity": "1", "rescued": False},
                {"lot": str(foreign_lot.pk), "quantity": "3", "rescued": False},
            ],
        )
        body = get_meal_detail(self.client, suggestion)
        entries = body["ingredients"][0]["allocations"]
        assert [e["lot_id"] for e in entries] == [str(own_lot.pk)]
        assert str(foreign_lot.pk) not in json.dumps(body)

    def test_malformed_allocation_entry_is_omitted_safely(self):
        """An allocation quantity that cannot be parsed exactly is
        dropped from the output; it is never rendered with a guessed
        value and never leaks other data."""

        suggestion = make_suggestion(self.user, title="Bad Allocation")
        lot = make_lot(self.user, "Onion", "1.000", unit="count")
        MealIngredient.objects.create(
            suggestion=suggestion,
            household=self.user.household,
            name="Onion",
            unit="count",
            required_quantity=Decimal("1.000"),
            owned_quantity=Decimal("1.000"),
            missing_quantity=Decimal("0.000"),
            rescued=False,
            allocations=[{"lot": str(lot.pk), "quantity": "not-a-number"}],
        )
        body = get_meal_detail(self.client, suggestion)
        assert body["ingredients"][0]["allocations"] == []
        assert body["ingredients"][0]["name"] == "Onion"


class MealGenerateAuthTests(TestCase):
    """POST /api/v1/meals/generate/ — auth and CSRF boundaries."""

    def setUp(self):
        self.user = make_user("meal-gen-user")
        # Real CSRF enforcement, matching the inventory API test suite.
        self.client = Client(enforce_csrf_checks=True)

    def _post(self, client, csrf=None):
        headers = {}
        if csrf is not None:
            headers["HTTP_X_CSRFTOKEN"] = csrf
        return client.post(
            reverse(MEAL_GENERATE),
            data=json.dumps(
                {
                    "servings": 2,
                    "max_minutes": 30,
                    "dietary_exclusions": ["nuts"],
                    "preference": "light",
                    "include_expired": False,
                }
            ),
            content_type="application/json",
            **headers,
        )

    def test_anonymous_returns_envelope(self):
        client = Client(enforce_csrf_checks=True)
        response = self._post(client)
        assert response.status_code == 403, response.content
        assert error_body(response)["code"] == "not_authenticated"
        assert MealSuggestion.objects.count() == 0

    def test_missing_csrf_returns_envelope_without_writes(self):
        # Logged in (the setUp client would otherwise be anonymous and the
        # 403 would be not_authenticated, not csrf_failed).
        login(self.client, self.user)
        # Real browser CSRF handshake: render the dashboard so the csrftoken
        # cookie is set, then POST without the X-CSRFToken header.
        response = self.client.get(reverse("inventory:dashboard"))
        assert response.status_code == 200
        token = self.client.cookies["csrftoken"].value
        assert token
        self.client.cookies["csrftoken"] = "stale-token"
        with _patch_provider(FakeProvider()):
            response = self._post(self.client)
        assert response.status_code == 403, response.content
        assert error_body(response)["code"] == "csrf_failed"
        assert MealSuggestion.objects.count() == 0

    def test_invalid_csrf_token_returns_envelope_without_writes(self):
        login(self.client, self.user)
        self.client.get(reverse("inventory:dashboard"))
        self.client.cookies["csrftoken"] = "bogus-token"
        with _patch_provider(FakeProvider()):
            response = self._post(self.client)
        assert response.status_code == 403, response.content
        assert error_body(response)["code"] == "csrf_failed"
        assert MealSuggestion.objects.count() == 0

    def test_wrong_method_returns_405_envelope(self):
        login(self.client, self.user)
        response = self.client.get(reverse(MEAL_GENERATE))
        assert response.status_code == 405
        assert error_body(response)["code"] == "method_not_allowed"


def _patch_provider(fake):
    from unittest.mock import patch

    return patch.object(meal_services, "get_provider", return_value=fake)


class MealGenerateSuccessTests(TestCase):
    """POST /api/v1/meals/generate/ — success path and exactly-once calls."""

    def setUp(self):
        self.user = make_user("meal-gen-success")
        self.client = Client(enforce_csrf_checks=True)
        login(self.client, self.user)
        # Real browser CSRF handshake: the dashboard sets the csrftoken cookie.
        response = self.client.get(reverse("inventory:dashboard"))
        assert response.status_code == 200
        self._csrf = self.client.cookies["csrftoken"].value

    def _post_body(self, **overrides):
        body = {
            "servings": 2,
            "max_minutes": 30,
            "dietary_exclusions": ["nuts", "dairy"],
            "preference": "light",
            "include_expired": False,
        }
        body.update(overrides)
        return self.client.post(
            reverse(MEAL_GENERATE),
            data=json.dumps(body),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf,
        )

    def test_success_creates_suggestion_and_returns_location(self):
        fake = FakeProvider()
        with _patch_provider(fake):
            response = self._post_body()
        assert response.status_code == 201, response.content
        body = response.json()
        assert body["status"] == "suggested"
        assert body["title"] == "Garlicky onion stir-fry"
        assert body["servings"] == 2
        assert body["time_minutes"] == 25
        assert body["provider_model"] == "fake-model"
        assert body["cooked_at"] is None
        assert response.headers["Location"] == f"/api/v1/meals/{body['id']}/"
        assert len(body["ingredients"]) == 2
        # Exactly one service-level provider call.
        assert len(fake.calls) == 1
        reqs = fake.calls[0]["requirements"]
        assert reqs["servings"] == 2
        assert reqs["max_minutes"] == 30
        assert reqs["dietary_exclusions"] == "nuts, dairy"
        assert reqs["preference"] == "light"
        assert reqs["include_expired"] is False
        # One suggestion and its ingredients were persisted.
        assert self.user.household.meal_suggestions.count() == 1

    def test_optional_body_fields_default(self):
        fake = FakeProvider()
        with _patch_provider(fake):
            response = self.client.post(
                reverse(MEAL_GENERATE),
                data=json.dumps({"servings": 2, "max_minutes": 30}),
                content_type="application/json",
                HTTP_X_CSRFTOKEN=self._csrf,
            )
        assert response.status_code == 201, response.content
        reqs = fake.calls[0]["requirements"]
        assert reqs["dietary_exclusions"] == ""
        assert reqs["preference"] == ""
        assert reqs["include_expired"] is False


class MealGenerateFailureTests(TestCase):
    """Provider/config failures map to stable envelopes with zero writes."""

    def setUp(self):
        self.user = make_user("meal-gen-fail")
        self.client = Client(enforce_csrf_checks=True)
        login(self.client, self.user)
        response = self.client.get(reverse("inventory:dashboard"))
        assert response.status_code == 200
        self._csrf = self.client.cookies["csrftoken"].value

    def _post(self, body=None):
        return self.client.post(
            reverse(MEAL_GENERATE),
            data=json.dumps(
                body or {"servings": 2, "max_minutes": 30}
            ),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf,
        )

    def test_provider_config_error_is_503_ai_unavailable(self):
        fake = FakeProvider(error=AIConfigError("missing key"))
        with _patch_provider(fake):
            response = self._post()
        assert response.status_code == 503, response.content
        assert error_body(response)["code"] == "ai_unavailable"
        assert MealSuggestion.objects.count() == 0
        assert self.user.household.lots.count() == 0

    def test_provider_request_error_is_503_ai_unavailable(self):
        fake = FakeProvider(error=AIRequestError("network down"))
        with _patch_provider(fake):
            response = self._post()
        assert response.status_code == 503, response.content
        assert error_body(response)["code"] == "ai_unavailable"
        assert MealSuggestion.objects.count() == 0

    def test_malformed_provider_output_is_422_invalid_provider_output(self):
        fake = FakeProvider(error=AIMalformedOutputError("bad shape"))
        with _patch_provider(fake):
            response = self._post()
        assert response.status_code == 422, response.content
        assert error_body(response)["code"] == "invalid_provider_output"
        assert MealSuggestion.objects.count() == 0

    def test_oversized_provider_output_is_422_invalid_provider_output(self):
        fake = FakeProvider(error=AIOutputTooLargeError("too big"))
        with _patch_provider(fake):
            response = self._post()
        assert response.status_code == 422
        assert error_body(response)["code"] == "invalid_provider_output"
        assert MealSuggestion.objects.count() == 0

    def test_generic_provider_error_is_503_ai_unavailable(self):
        fake = FakeProvider(error=AIProviderError("boom"))
        with _patch_provider(fake):
            response = self._post()
        assert response.status_code == 503
        assert error_body(response)["code"] == "ai_unavailable"
        assert MealSuggestion.objects.count() == 0

    def test_failure_leaks_no_provider_internals(self):
        fake = FakeProvider(error=AIRequestError("SECRET=api-key-xyz"))
        with _patch_provider(fake):
            response = self._post()
        assert response.status_code == 503
        text = response.content.decode()
        assert "api-key-xyz" not in text
        assert "SECRET" not in text

    def test_malformed_body_is_400_validation_error(self):
        cases = (
            {"servings": 0, "max_minutes": 30},
            {"servings": 51, "max_minutes": 30},
            {"servings": 2, "max_minutes": 4},
            {"servings": 2, "max_minutes": 601},
            {"servings": "two", "max_minutes": 30},
            {"servings": 2, "max_minutes": 30, "dietary_exclusions": ["a"] * 21},
            {"servings": 2, "max_minutes": 30, "preference": "x" * 201},
            {"servings": 2, "max_minutes": 30, "dietary_exclusions": [""]},
        )
        for body in cases:
            fake = FakeProvider()
            with _patch_provider(fake):
                response = self._post(body)
            assert response.status_code == 400, (body, response.status_code)
            assert error_body(response)["code"] == "validation_error"
            assert len(fake.calls) == 0
        assert MealSuggestion.objects.count() == 0

    def test_malformed_json_body_is_400_parse_error(self):
        response = self.client.post(
            reverse(MEAL_GENERATE),
            data="{not json",
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf,
        )
        assert response.status_code == 400
        assert error_body(response)["code"] == "parse_error"

    def test_unsupported_media_type_is_415(self):
        response = self.client.post(
            reverse(MEAL_GENERATE),
            data="<xml/>",
            content_type="application/xml",
            HTTP_X_CSRFTOKEN=self._csrf,
        )
        assert response.status_code == 415
        assert error_body(response)["code"] == "unsupported_media_type"

    def test_no_writes_on_any_failure_path(self):
        for error in (
            AIConfigError("no key"),
            AIRequestError("timeout"),
            AIOutputTooLargeError("big"),
        ):
            fake = FakeProvider(error=error)
            with _patch_provider(fake):
                response = self._post()
            assert response.status_code in (422, 503)
            assert MealSuggestion.objects.count() == 0
            assert self.user.household.meal_suggestions.count() == 0
            assert self.user.household.lots.count() == 0


class MealCookTests(TestCase):
    """POST /api/v1/meals/<uuid>/cook/ — exactly-once, conflict, rollback."""

    def setUp(self):
        self.user = make_user("meal-cook-user")
        self.other = make_user("meal-cook-other")
        self.client = Client(enforce_csrf_checks=True)
        login(self.client, self.user)
        response = self.client.get(reverse("inventory:dashboard"))
        assert response.status_code == 200
        self._csrf = self.client.cookies["csrftoken"].value

    def _cookable_suggestion(self, owner=None):
        """A suggestion whose allocations exactly match live lot balances."""
        owner = owner or self.user
        suggestion = make_suggestion(owner, title="Cookable Meal")
        lot = make_lot(owner, "Onion", "3.000", unit="count")

        MealIngredient.objects.create(
            suggestion=suggestion,
            household=owner.household,
            name="Onion",
            unit="count",
            required_quantity=Decimal("3.000"),
            owned_quantity=Decimal("3.000"),
            missing_quantity=Decimal("0.000"),
            rescued=False,
            allocations=[{"lot": str(lot.pk), "quantity": "3", "rescued": False}],
        )
        return suggestion, lot

    def _post(self, suggestion, client=None):
        client = client or self.client
        return client.post(
            reverse(MEAL_COOK, args=[suggestion.pk]),
            data=json.dumps({}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf,
        )

    def test_anonymous_returns_envelope(self):
        suggestion, _ = self._cookable_suggestion()
        client = Client()
        response = client.post(
            reverse(MEAL_COOK, args=[suggestion.pk]),
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 403
        assert error_body(response)["code"] == "not_authenticated"
        assert MealEvent.objects.count() == 0

    def test_missing_csrf_returns_envelope_without_writes(self):
        suggestion, _ = self._cookable_suggestion()
        response = self.client.post(
            reverse(MEAL_COOK, args=[suggestion.pk]),
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 403, response.content
        assert error_body(response)["code"] == "csrf_failed"
        assert MealEvent.objects.count() == 0

    def test_foreign_suggestion_is_404(self):
        suggestion, _ = self._cookable_suggestion(owner=self.other)
        response = self._post(suggestion)
        assert response.status_code == 404
        assert error_body(response)["code"] == "not_found"
        assert MealEvent.objects.count() == 0

    def test_unknown_uuid_is_404(self):
        response = self.client.post(
            reverse(MEAL_COOK, args=[uuid.uuid4()]),
            data=json.dumps({}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf,
        )
        assert response.status_code == 404
        assert error_body(response)["code"] == "not_found"

    def test_wrong_method_on_cook_is_405(self):
        suggestion, _ = self._cookable_suggestion()
        response = self.client.get(reverse(MEAL_COOK, args=[suggestion.pk]))
        assert response.status_code == 405
        assert error_body(response)["code"] == "method_not_allowed"

    def test_cook_success_updates_status_and_cooked_at(self):
        suggestion, lot = self._cookable_suggestion()
        balance_before = services.lot_balance(lot)
        assert balance_before == Decimal("3.000")
        response = self._post(suggestion)
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["status"] == "cooked"
        assert body["cooked_at"] is not None
        suggestion.refresh_from_db()
        assert suggestion.status == MealSuggestion.Status.COOKED
        assert body["cooked_at"] == api_timestamp(suggestion.meal_event.cooked_at)
        assert services.lot_balance(lot) == Decimal("0.000")
        # Exactly one consume event was written for the lot.
        assert (
            self.user.household.events.filter(
                event_type=InventoryEvent.EventType.CONSUME, lot=lot
            ).count()
            == 1
        )

    def test_duplicate_cook_is_409_already_cooked_with_zero_writes(self):
        suggestion, lot = self._cookable_suggestion()
        first = self._post(suggestion)
        assert first.status_code == 200
        balance_after_first = services.lot_balance(lot)
        second = self._post(suggestion)
        assert second.status_code == 409
        assert error_body(second)["code"] == "already_cooked"
        assert services.lot_balance(lot) == balance_after_first
        assert MealEvent.objects.count() == 1

    def test_rejected_suggestion_cook_is_409_cook_conflict(self):
        suggestion, _ = self._cookable_suggestion()
        suggestion.status = MealSuggestion.Status.REJECTED
        suggestion.save()
        response = self._post(suggestion)
        assert response.status_code == 409
        assert error_body(response)["code"] == "cook_conflict"
        assert MealEvent.objects.count() == 0

    def test_stale_allocation_cook_is_409_and_rolls_back(self):
        suggestion, lot = self._cookable_suggestion()
        # Simulate a stale snapshot: drain the lot through the service layer
        # so the suggestion's allocation no longer matches live balances.
        services.consume_stock(
            household=self.user.household,
            lot=lot,
            quantity=Decimal("3.000"),
            unit="count",
            note="drained before cook",
        )
        response = self._post(suggestion)
        assert response.status_code == 409, response.content
        assert error_body(response)["code"] == "cook_conflict"
        suggestion.refresh_from_db()
        assert suggestion.status == MealSuggestion.Status.SUGGESTED
        assert MealEvent.objects.count() == 0

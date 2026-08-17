"""Meal suggestion tests.

Covers: inventory snapshot household isolation and expiry rules/boundaries;
structured validator edge cases; provider failure taxonomy (timeout, HTTP,
network, malformed JSON, oversized) with zero rows and zero inventory
events; deterministic reconciliation across partial/multiple lots;
unsupported/mismatched units; auth/CSRF/PRG; result rendering; history;
cross-household GET/POST isolation; and proposal immutability.

No test calls the network: the provider is either a deterministic fake
patched onto the generation service, or the real OpenAI-compatible
implementation with ``urllib.request.urlopen`` patched.
"""

from datetime import timedelta
from decimal import Decimal
import json
import os
import socket
import urllib.error
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from inventory import exceptions, meal_services, services
from inventory.ai import openai as openai_module
from inventory.ai.exceptions import (
    AIConfigError,
    AIMalformedOutputError,
    AIOutputTooLargeError,
    AIProviderError,
    AIRequestError,
)
from inventory.ai.schema import validate_proposal
from inventory.models import (
    InventoryEvent,
    MealEvent,
    MealIngredient,
    MealSuggestion,
)
from inventory.tests.test_views import make_lot, make_user

User = get_user_model()

SUGGEST = "inventory:meal_suggest"
HISTORY = "inventory:meal_history"
DETAIL = "inventory:meal_detail"
LOGIN = "inventory:login"

FORM_DATA = {
    "servings": "2",
    "max_minutes": "30",
    "dietary_exclusions": "nuts",
    "preference": "something light",
    "include_expired": "",
}


def valid_payload(**overrides):
    payload = {
        "title": "Garlicky onion stir-fry",
        "servings": 2,
        "time_minutes": 25,
        "steps": ["Chop the onion.", "Stir-fry with garlic."],
        "substitutions": ["Olive oil instead of butter."],
        "safety_note": "Mind the hot pan.",
        "rationale": "Uses the onions that expire soon.",
        "ingredients": [
            {"name": "Onion", "unit": "count", "quantity": 3},
            {"name": "garlic", "unit": "g", "quantity": 10},
        ],
    }
    payload.update(overrides)
    return payload


class FakeProvider:
    """Deterministic provider stand-in (no network)."""

    model_name = "fake-model"

    def __init__(self, payload=None, error=None):
        self.payload = payload if payload is not None else valid_payload()
        self.error = error
        self.calls = []

    def generate(self, snapshot, requirements):
        self.calls.append({"snapshot": snapshot, "requirements": requirements})
        if self.error is not None:
            raise self.error
        return self.payload


def snapshot_map(snapshot):
    return {item["product"]: item for item in snapshot}


def lot_balances(user):
    """Derived balance of every lot, keyed by product name + lot pk."""
    return {
        (lot.product.name, str(lot.pk)): services.lot_balance(lot)
        for lot in user.household.lots.all()
    }


class FakeHTTPResponse:
    """Minimal stand-in for the ``urlopen`` context manager result."""

    def __init__(self, body):
        self._body = body

    def read(self, n=-1):
        if n is None or n < 0:
            return self._body
        return self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def chat_response(payload_content):
    """Bytes of a successful chat-completions envelope around ``content``."""
    return json.dumps(
        {"choices": [{"message": {"content": payload_content}}]}
    ).encode("utf-8")


class SnapshotTests(TestCase):
    """Structured snapshot: household isolation, expiry rules, boundaries."""

    def setUp(self):
        self.user_a = make_user("snap_a")
        self.user_b = make_user("snap_b")
        self.today = timezone.localdate()
        a = self.user_a
        self.lot_expired = make_lot(a, "Onion", 5, "count",
                                    expires_on=self.today - timedelta(days=7))
        self.lot_today = make_lot(a, "Garlic", 10, "g",
                                  expires_on=self.today)
        self.lot_plus1 = make_lot(a, "Pepper", 2, "count",
                                  expires_on=self.today + timedelta(days=1))
        self.lot_plus2 = make_lot(a, "Tomato", 3, "count",
                                  expires_on=self.today + timedelta(days=2))
        self.lot_plus3 = make_lot(a, "Lettuce", 1, "count",
                                  expires_on=self.today + timedelta(days=3))
        self.lot_nodate = make_lot(a, "Flour", 500, "g")
        # Zero-balance lot: add 5, consume 5.
        chili = make_lot(a, "Chili", 5, "count")
        services.consume_stock(
            household=a.household, lot=chili, quantity=Decimal("5"),
            unit="count", note="zero out",
        )
        self.lot_zero = chili
        make_lot(self.user_b, "Saffron", 1, "count")

    def test_default_snapshot_excludes_expired_and_zero_balance(self):
        snapshot = meal_services.build_inventory_snapshot(self.user_a.household)
        names = [item["product"] for item in snapshot]
        self.assertEqual(
            names,
            ["Garlic", "Pepper", "Tomato", "Lettuce", "Flour"],
        )
        self.assertNotIn("Onion", names)
        self.assertNotIn("Chili", names)

    def test_expiry_flags_and_boundaries(self):
        snapshot = meal_services.build_inventory_snapshot(self.user_a.household)
        flags = snapshot_map(snapshot)
        # Boundary: today..today+2 are the priority window.
        self.assertEqual(flags["Garlic"]["expiry"], "expiry_soon")
        self.assertEqual(flags["Pepper"]["expiry"], "expiry_soon")
        self.assertEqual(flags["Tomato"]["expiry"], "expiry_soon")
        # today+3 is outside the window.
        self.assertEqual(flags["Lettuce"]["expiry"], "later")
        self.assertEqual(flags["Flour"]["expiry"], "no_date")
        self.assertIsNone(flags["Flour"]["expires_on"])
        self.assertEqual(flags["Garlic"]["expires_on"],
                         self.today.isoformat())
        self.assertEqual(Decimal(flags["Garlic"]["available"]),
                         Decimal("10.000"))
        self.assertEqual(flags["Garlic"]["unit"], "g")

    def test_expired_included_only_when_explicitly_confirmed(self):
        default = meal_services.build_inventory_snapshot(self.user_a.household)
        self.assertNotIn("Onion", [item["product"] for item in default])
        confirmed = meal_services.build_inventory_snapshot(
            self.user_a.household, include_expired=True
        )
        onion = snapshot_map(confirmed)["Onion"]
        self.assertEqual(onion["expiry"], "expired")

    def test_snapshot_is_household_isolated(self):
        snapshot = meal_services.build_inventory_snapshot(self.user_b.household)
        self.assertEqual([item["product"] for item in snapshot], ["Saffron"])

    def test_snapshot_omits_products_outside_household_even_with_same_name(self):
        # Household B has no "Saffron" lot; A's lots must not leak in.
        snapshot = meal_services.build_inventory_snapshot(self.user_a.household)
        self.assertNotIn("Saffron", [item["product"] for item in snapshot])

    def test_requirements_are_passed_to_the_provider(self):
        fake = FakeProvider()
        with mock.patch.object(meal_services, "get_provider",
                               return_value=fake):
            meal_services.generate_suggestion(
                household=self.user_a.household,
                servings=4,
                max_minutes=90,
                dietary_exclusions="dairy",
                preference="warm",
                include_expired=True,
            )
        (call,) = fake.calls
        self.assertEqual(
            call["requirements"],
            {
                "servings": 4,
                "max_minutes": 90,
                "dietary_exclusions": "dairy",
                "preference": "warm",
                "include_expired": True,
            },
        )
        # Expired lot is visible only because it was explicitly confirmed.
        self.assertEqual(snapshot_map(call["snapshot"])["Onion"]["expiry"],
                         "expired")


class ValidatorTests(TestCase):
    """Structured validator edge cases (no provider, no database writes)."""

    def test_valid_payload_is_normalized(self):
        proposal = validate_proposal(
            valid_payload(title="  Pad  Thaai  ", ingredients=[
                {"name": "   Onion   ", "unit": "count", "quantity": "2.500"},
                {"name": "garlic", "unit": "g", "quantity": 10},
            ]),
            provider_model="m",
        )
        self.assertEqual(proposal.title, "Pad Thaai")
        self.assertEqual(proposal.servings, 2)
        self.assertEqual(proposal.time_minutes, 25)
        self.assertEqual(proposal.steps, ("Chop the onion.",
                                          "Stir-fry with garlic."))
        self.assertEqual(proposal.ingredients[0].name, "Onion")
        self.assertEqual(proposal.ingredients[0].quantity, Decimal("2.500"))
        self.assertEqual(proposal.ingredients[1].unit, "g")
        self.assertEqual(proposal.provider_model, "m")

    def _expect_rejected(self, label, payload):
        with self.assertRaises(AIMalformedOutputError, msg=label):
            validate_proposal(payload)

    def test_rejects_non_object_payload(self):
        self._expect_rejected("list payload", [valid_payload()])
        self._expect_rejected("string payload", "{}")
        self._expect_rejected("null payload", None)

    def test_title_rules(self):
        p = valid_payload()
        p.pop("title")
        self._expect_rejected("missing title", p)
        self._expect_rejected("blank title", valid_payload(title="   "))
        self._expect_rejected(
            "201-char title", valid_payload(title="x" * 201)
        )
        # 200 chars is allowed:
        validate_proposal(valid_payload(title="x" * 200))

    def test_servings_rules(self):
        for bad in (0, -1, 51, "2", 2.0, True, None):
            self._expect_rejected(
                f"servings={bad!r}", valid_payload(servings=bad)
            )
        validate_proposal(valid_payload(servings=1))
        validate_proposal(valid_payload(servings=50))

    def test_time_rules(self):
        for bad in (0, 4, -5, 601, "30", False):
            self._expect_rejected(
                f"time={bad!r}", valid_payload(time_minutes=bad)
            )
        validate_proposal(valid_payload(time_minutes=5))
        validate_proposal(valid_payload(time_minutes=600))

    def test_steps_rules(self):
        p = valid_payload()
        p.pop("steps")
        self._expect_rejected("missing steps", p)
        self._expect_rejected("empty steps", valid_payload(steps=[]))
        self._expect_rejected("steps not list", valid_payload(steps="a"))
        self._expect_rejected(
            "non-string step", valid_payload(steps=[123])
        )
        self._expect_rejected(
            "empty step", valid_payload(steps=[" ", "ok"])
        )
        self._expect_rejected(
            "step too long", valid_payload(steps=["x" * 501])
        )
        self._expect_rejected(
            "too many steps", valid_payload(steps=[f"s{i}" for i in range(51)])
        )

    def test_substitutions_rules(self):
        self._expect_rejected(
            "substitutions not list", valid_payload(substitutions="no")
        )
        self._expect_rejected(
            "too many substitutions",
            valid_payload(substitutions=[f"s{i}" for i in range(21)]),
        )
        # Absent is fine.
        p = valid_payload()
        p.pop("substitutions")
        self.assertEqual(validate_proposal(p).substitutions, ())

    def test_safety_note_and_rationale_rules(self):
        self._expect_rejected(
            "safety note too long", valid_payload(safety_note="x" * 501)
        )
        p = valid_payload()
        p.pop("rationale")
        self._expect_rejected("missing rationale", p)
        self._expect_rejected("blank rationale", valid_payload(rationale=" "))
        self._expect_rejected(
            "rationale too long", valid_payload(rationale="x" * 2001)
        )

    def test_ingredient_structure_rules(self):
        p = valid_payload()
        p.pop("ingredients")
        self._expect_rejected("missing ingredients", p)
        self._expect_rejected("empty ingredients", valid_payload(ingredients=[]))
        self._expect_rejected(
            "ingredients not list", valid_payload(ingredients="onion")
        )
        self._expect_rejected(
            "too many ingredients",
            valid_payload(
                ingredients=[
                    {"name": f"I{i}", "unit": "count", "quantity": 1}
                    for i in range(31)
                ]
            ),
        )
        self._expect_rejected(
            "ingredient not object", valid_payload(ingredients=["onion"])
        )
        self._expect_rejected(
            "missing name",
            valid_payload(
                ingredients=[{"unit": "count", "quantity": 1}]
            ),
        )
        self._expect_rejected(
            "blank name",
            valid_payload(
                ingredients=[{"name": "   ", "unit": "count", "quantity": 1}]
            ),
        )
        self._expect_rejected(
            "name too long",
            valid_payload(
                ingredients=[{"name": "x" * 101, "unit": "count", "quantity": 1}]
            ),
        )

    def test_unsupported_or_mismatched_units(self):
        for bad in ("stone", "G", "grams", "grams ", "", 5, None):
            self._expect_rejected(
                f"unit={bad!r}",
                valid_payload(ingredients=[{"name": "Onion", "unit": bad,
                                            "quantity": 1}]),
            )
        for good in ("count", "each", "g", "kg", "ml", "l"):
            validate_proposal(
                valid_payload(ingredients=[{"name": "Onion", "unit": good,
                                            "quantity": 1}])
            )

    def test_quantity_rules(self):
        def bad_quantity(value, label):
            self._expect_rejected(
                label,
                valid_payload(
                    ingredients=[{"name": "Onion", "unit": "count",
                                  "quantity": value}]
                ),
            )

        bad_quantity(0, "zero quantity")
        bad_quantity(-3, "negative quantity")
        bad_quantity("1.2345", "4 decimal places")
        bad_quantity(0.0001, "non-exact float")
        bad_quantity(float("nan"), "NaN float")
        bad_quantity(float("inf"), "infinite float")
        bad_quantity("NaN", "NaN string")
        bad_quantity("Infinity", "Infinity string")
        bad_quantity("abc", "non-numeric string")
        bad_quantity(None, "missing quantity")
        bad_quantity(True, "boolean quantity")
        bad_quantity(10 ** 10, "oversized quantity")
        # Exact and positive values are accepted, including strings/ints.
        proposal = validate_proposal(
            valid_payload(
                ingredients=[{"name": "Onion", "unit": "count",
                              "quantity": " 3 "}]
            )
        )
        self.assertEqual(proposal.ingredients[0].quantity, Decimal("3"))

    def test_fractional_json_floats_parse_as_their_decimal_values(self):
        # Regression: provider JSON numbers like 0.1 decode to Python
        # floats; validation must preserve the decimal JSON value, not the
        # float's binary expansion (Decimal(0.1) is 0.10000000000000000555...
        # and failed the 3-dp-exact rule).
        for value, exact in ((0.1, "0.1"), (0.2, "0.2"), (0.3, "0.3"),
                             (1.1, "1.1"), (0.5, "0.5"), (1.25, "1.25"),
                             (0.001, "0.001")):
            proposal = validate_proposal(
                valid_payload(
                    ingredients=[{"name": "Onion", "unit": "g",
                                  "quantity": value}]
                )
            )
            self.assertEqual(proposal.ingredients[0].quantity,
                             Decimal(exact), msg=f"quantity {value!r}")

    def test_imprecise_or_out_of_range_floats_still_rejected(self):
        # 4 decimal places in the JSON literal.
        self._expect_rejected("0.0001", valid_payload(ingredients=[
            {"name": "Onion", "unit": "g", "quantity": 0.0001}]))
        # 0.1 + 0.2 is 0.30000000000000004, not 0.3.
        self._expect_rejected("0.1+0.2 float", valid_payload(ingredients=[
            {"name": "Onion", "unit": "g", "quantity": 0.1 + 0.2}]))
        # Negative float.
        self._expect_rejected("-0.1", valid_payload(ingredients=[
            {"name": "Onion", "unit": "g", "quantity": -0.1}]))
        # Oversized float (1e10 > MAX_QUANTITY).
        self._expect_rejected("1e10", valid_payload(ingredients=[
            {"name": "Onion", "unit": "g", "quantity": 1e10}]))

    def test_duplicate_ingredient_rejected(self):
        payload = valid_payload(ingredients=[
            {"name": "Onion", "unit": "count", "quantity": 1},
            {"name": "  oNiOn ", "unit": "count", "quantity": 2},
        ])
        self._expect_rejected("duplicate name", payload)
        # Same name, different unit is allowed (distinct products).
        validate_proposal(valid_payload(ingredients=[
            {"name": "Onion", "unit": "count", "quantity": 1},
            {"name": "Onion", "unit": "g", "quantity": 10},
        ]))


class OpenAIProviderTests(TestCase):
    """The OpenAI-compatible HTTP implementation, with urlopen patched."""

    ENV = {
        "AI_BASE_URL": "http://ai.test",
        "AI_MODEL": "test-model",
        "AI_API_KEY": "",
        "AI_TIMEOUT": "",
    }

    def _provider(self, env=None):
        return openai_module.OpenAICompatibleProvider()

    def test_configured_request_shape(self):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeHTTPResponse(
                chat_response(json.dumps(valid_payload()))
            )

        with mock.patch.dict(os.environ, self.ENV):
            with mock.patch.object(openai_module.urllib.request, "urlopen",
                                   fake_urlopen) as patched:
                provider = self._provider()
                payload = provider.generate([{"id": "1"}], {"servings": 2})
        self.assertEqual(payload["title"], "Garlicky onion stir-fry")
        request = captured["request"]
        self.assertEqual(request.full_url,
                         "http://ai.test/chat/completions")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertIsNone(request.get_header("Authorization"))
        self.assertEqual(captured["timeout"], 30.0)
        body = json.loads(request.data)
        self.assertEqual(body["model"], "test-model")
        self.assertEqual(len(body["messages"]), 2)
        self.assertEqual(body["messages"][0]["role"], "system")
        user_message = json.loads(body["messages"][1]["content"])
        self.assertEqual(user_message["inventory"], [{"id": "1"}])
        self.assertEqual(user_message["requirements"], {"servings": 2})

    def test_bearer_header_sent_only_when_key_set(self):
        def fake_urlopen(request, timeout=None):
            captured["headers"] = dict(request.headers)
            return FakeHTTPResponse(chat_response(json.dumps(valid_payload())))

        captured = {}
        with mock.patch.dict(os.environ, {**self.ENV, "AI_API_KEY": "k-123"}):
            with mock.patch.object(openai_module.urllib.request, "urlopen",
                                   fake_urlopen):
                self._provider().generate([], {})
        self.assertEqual(captured["headers"].get("Authorization"), "Bearer k-123")

    def test_fractional_json_numbers_are_exact_after_provider_parse(self):
        # Real JSON round trip: the completion's "0.1" decodes to the float
        # 0.1 and must validate to Decimal("0.1"), not the binary expansion.
        payload = valid_payload(ingredients=[
            {"name": "Onion", "unit": "g", "quantity": 0.1},
            {"name": "Flour", "unit": "kg", "quantity": 0.2},
            {"name": "Pepper", "unit": "count", "quantity": 0.3},
            {"name": "Garlic", "unit": "l", "quantity": 1.1},
        ])
        with mock.patch.dict(os.environ, self.ENV):
            with mock.patch.object(openai_module.urllib.request, "urlopen",
                                   return_value=FakeHTTPResponse(
                                       chat_response(json.dumps(payload)))):
                decoded = self._provider().generate([], {})
        proposal = validate_proposal(decoded, provider_model="test-model")
        self.assertEqual(
            [i.quantity for i in proposal.ingredients],
            [Decimal("0.1"), Decimal("0.2"), Decimal("0.3"),
             Decimal("1.1")],
        )

    def test_missing_config_raises_config_error(self):
        cases = (
            {},
            {"AI_MODEL": "m"},
            {"AI_BASE_URL": "http://ai.test"},
            {"AI_BASE_URL": "", "AI_MODEL": "m"},
        )
        for env in cases:
            with mock.patch.dict(os.environ, clear=True):
                os.environ.update(env)
                with self.assertRaises(AIConfigError):
                    self._provider()

    def test_invalid_timeout_values_raise_config_error(self):
        for bad in ("abc", "0", "-1", "130"):
            with mock.patch.dict(
                os.environ, {**self.ENV, "AI_TIMEOUT": bad}
            ):
                with self.assertRaises(AIConfigError):
                    self._provider()
        with mock.patch.dict(
            os.environ, {**self.ENV, "AI_TIMEOUT": "45"}
        ):
            self.assertEqual(self._provider().timeout, 45.0)

    def _call_with(self, side_effect):
        with mock.patch.dict(os.environ, self.ENV):
            with mock.patch.object(openai_module.urllib.request, "urlopen",
                                   side_effect=side_effect):
                return self._provider().generate([], {})

    def test_timeout_raises_request_error(self):
        with self.assertRaises(AIRequestError) as cm:
            self._call_with(socket.timeout("boom"))
        self.assertIn("timed out", str(cm.exception))

    def test_http_error_raises_request_error(self):
        error = urllib.error.HTTPError("http://ai.test/chat/completions", 500,
                                       "err", None, None)
        with self.assertRaises(AIRequestError) as cm:
            self._call_with(error)
        self.assertIn("HTTP 500", str(cm.exception))

    def test_network_error_raises_request_error(self):
        with self.assertRaises(AIRequestError) as cm:
            self._call_with(urllib.error.URLError("unreachable"))
        self.assertIn("unreachable", str(cm.exception))

    def test_top_level_invalid_json_raises_malformed(self):
        with mock.patch.dict(os.environ, self.ENV):
            with mock.patch.object(openai_module.urllib.request, "urlopen",
                                   return_value=FakeHTTPResponse(b"oops")):
                with self.assertRaises(AIMalformedOutputError) as cm:
                    self._provider().generate([], {})
        self.assertIn("not valid JSON", str(cm.exception))

    def test_missing_completion_structure_raises_malformed(self):
        with mock.patch.dict(os.environ, self.ENV):
            with mock.patch.object(openai_module.urllib.request, "urlopen",
                                   return_value=FakeHTTPResponse(
                                       b'{"foo": 1}')):
                with self.assertRaises(AIMalformedOutputError) as cm:
                    self._provider().generate([], {})
        self.assertIn("completion payload", str(cm.exception))

    def test_non_string_content_raises_malformed(self):
        with mock.patch.dict(os.environ, self.ENV):
            with mock.patch.object(openai_module.urllib.request, "urlopen",
                                   return_value=FakeHTTPResponse(
                                       json.dumps(
                                           {"choices": [
                                               {"message": {"content": 42}}
                                           ]}
                                       ).encode("utf-8"))):
                with self.assertRaises(AIMalformedOutputError):
                    self._provider().generate([], {})

    def test_completion_not_json_raises_malformed(self):
        with mock.patch.dict(os.environ, self.ENV):
            with mock.patch.object(openai_module.urllib.request, "urlopen",
                                   return_value=FakeHTTPResponse(
                                       chat_response("sorry, plain text"))):
                with self.assertRaises(AIMalformedOutputError) as cm:
                    self._provider().generate([], {})
        self.assertIn("not valid JSON", str(cm.exception))

    def test_oversized_response_raises_size_error(self):
        oversized = b"x" * (openai_module.MAX_RESPONSE_BYTES + 1)
        with mock.patch.dict(os.environ, self.ENV):
            with mock.patch.object(openai_module.urllib.request, "urlopen",
                                   return_value=FakeHTTPResponse(oversized)):
                with self.assertRaises(AIOutputTooLargeError):
                    self._provider().generate([], {})


class ViewFailureTests(TestCase):
    """Provider failures at the form: recoverable banner, zero rows,
    zero inventory events, zero balance changes."""

    #: Provider configured so the failure tests reach the (patched) HTTP
    #: layer instead of a config error.
    AI_ENV = {
        "AI_BASE_URL": "http://ai.test",
        "AI_MODEL": "test-model",
        "AI_API_KEY": "",
        "AI_TIMEOUT": "",
    }

    def setUp(self):
        super().setUp()
        self.env_patcher = mock.patch.dict(os.environ, self.AI_ENV,
                                           clear=False)
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)
        self.user = make_user("fail_user")
        self.client.login(username="fail_user", password="sup3r-s3cr3t-pass")
        self.lot = make_lot(self.user, "Onion", 5, "count",
                            expires_on=timezone.localdate())
        self.event_count = InventoryEvent.objects.count()

    def _post_and_expect_failure(self, fragment):
        response = self.client.post(reverse(SUGGEST), FORM_DATA)
        self.assertEqual(response.status_code, 200)
        self.assertIn(fragment.encode("utf-8"), response.content)
        self.assertEqual(MealSuggestion.objects.count(), 0)
        self.assertEqual(MealIngredient.objects.count(), 0)
        self.assertEqual(InventoryEvent.objects.count(), self.event_count)
        from inventory import services

        self.assertEqual(services.lot_balance(self.lot), Decimal("5.000"))

    def test_disabled_provider_shows_config_error(self):
        with mock.patch.dict(os.environ, {"AI_BASE_URL": "", "AI_MODEL": ""},
                             clear=False):
            self._post_and_expect_failure("not configured")

    def test_timeout_shows_recoverable_error(self):
        with mock.patch.object(openai_module.urllib.request, "urlopen",
                               side_effect=socket.timeout("t")):
            self._post_and_expect_failure("timed out")

    def test_http_error_shows_recoverable_error(self):
        error = urllib.error.HTTPError("u", 500, "err", None, None)
        with mock.patch.object(openai_module.urllib.request, "urlopen",
                               side_effect=error):
            self._post_and_expect_failure("HTTP 500")

    def test_malformed_completion_shows_recoverable_error(self):
        with mock.patch.object(openai_module.urllib.request, "urlopen",
                               return_value=FakeHTTPResponse(
                                   chat_response("not json at all"))):
            self._post_and_expect_failure("not valid JSON")

    def test_oversized_completion_shows_recoverable_error(self):
        with mock.patch.object(openai_module.urllib.request, "urlopen",
                               return_value=FakeHTTPResponse(
                                   b"x" * (openai_module.MAX_RESPONSE_BYTES + 1))):
            self._post_and_expect_failure("larger than the allowed size")

    def test_schema_violation_end_to_end_shows_recoverable_error(self):
        # Real provider path + real validator: unsupported unit in the
        # completion content.
        with mock.patch.dict(os.environ, {
            "AI_BASE_URL": "http://ai.test", "AI_MODEL": "test-model",
            "AI_API_KEY": "", "AI_TIMEOUT": "",
        }):
            with mock.patch.object(
                openai_module.urllib.request, "urlopen",
                return_value=FakeHTTPResponse(chat_response(json.dumps(
                    valid_payload(ingredients=[
                        {"name": "Onion", "unit": "stone", "quantity": 1},
                    ]))))):
                self._post_and_expect_failure("must be one of")

    def test_imprecise_quantity_end_to_end_shows_recoverable_error(self):
        with mock.patch.dict(os.environ, {
            "AI_BASE_URL": "http://ai.test", "AI_MODEL": "test-model",
            "AI_API_KEY": "", "AI_TIMEOUT": "",
        }):
            with mock.patch.object(
                openai_module.urllib.request, "urlopen",
                return_value=FakeHTTPResponse(chat_response(json.dumps(
                    valid_payload(ingredients=[
                        {"name": "Onion", "unit": "count", "quantity": 1.2345},
                    ]))))):
                self._post_and_expect_failure("3 decimal places")

    def test_form_validation_error_renders_without_provider_call(self):
        fake = FakeProvider()
        with mock.patch.object(meal_services, "get_provider",
                               return_value=fake):
            response = self.client.post(reverse(SUGGEST),
                                        {**FORM_DATA, "servings": "0"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            b"Ensure this value is greater than or equal to 1",
            response.content,
        )
        self.assertEqual(fake.calls, [])
        self.assertEqual(MealSuggestion.objects.count(), 0)


class ReconciliationTests(TestCase):
    """Deterministic reconciliation against owned lots (fake provider)."""

    def setUp(self):
        self.user = make_user("recon_user")
        self.today = timezone.localdate()
        self.lot_onion_soon = make_lot(self.user, "Onion", 2, "count",
                                       expires_on=self.today)
        self.lot_onion_later = make_lot(self.user, "Onion", 3, "count",
                                        expires_on=self.today
                                        + timedelta(days=3))
        self.lot_garlic_soon = make_lot(self.user, "Garlic", 6, "g",
                                        expires_on=self.today)
        self.lot_garlic_nodate = make_lot(self.user, "Garlic", 4, "g")
        self.lot_flour = make_lot(self.user, "Flour", 500, "g")
        self.lot_kale_expired = make_lot(self.user, "Kale", 2, "count",
                                         expires_on=self.today
                                         - timedelta(days=3))
        # Zero-balance lot (add 1, consume 1).
        chili = make_lot(self.user, "Chili", 1, "count")
        services.consume_stock(household=self.user.household, lot=chili,
                               quantity=Decimal("1"), unit="count",
                               note="zero")
        self.lot_chili_zero = chili
        self.event_count = InventoryEvent.objects.count()
        self.balances_before = lot_balances(self.user)

    def _generate(self, ingredients, include_expired=False):
        fake = FakeProvider(payload=valid_payload(ingredients=ingredients))
        with mock.patch.object(meal_services, "get_provider",
                               return_value=fake):
            return meal_services.generate_suggestion(
                household=self.user.household,
                include_expired=include_expired,
            ), fake

    def test_partial_allocation_across_multiple_lots(self):
        suggestion, _ = self._generate([
            {"name": "Onion", "unit": "count", "quantity": 4},
        ])
        ingredient = suggestion.ingredients.get(name="Onion", unit="count")
        self.assertEqual(ingredient.required_quantity, Decimal("4.000"))
        self.assertEqual(ingredient.owned_quantity, Decimal("4.000"))
        self.assertEqual(ingredient.missing_quantity, Decimal("0.000"))
        self.assertEqual(len(ingredient.allocations), 2)
        # Expiry-priority lot is drawn first, even though it is smaller.
        self.assertEqual(ingredient.allocations[0]["lot"],
                         str(self.lot_onion_soon.pk))
        self.assertEqual(Decimal(ingredient.allocations[0]["quantity"]),
                         Decimal("2.000"))
        self.assertEqual(ingredient.allocations[1]["lot"],
                         str(self.lot_onion_later.pk))
        self.assertEqual(Decimal(ingredient.allocations[1]["quantity"]),
                         Decimal("2.000"))
        self.assertTrue(ingredient.rescued)

    def test_missing_quantity_when_nothing_owned(self):
        suggestion, _ = self._generate([
            {"name": "Saffron", "unit": "count", "quantity": 5},
        ])
        ingredient = suggestion.ingredients.get(name="Saffron")
        self.assertEqual(ingredient.owned_quantity, Decimal("0.000"))
        self.assertEqual(ingredient.missing_quantity, Decimal("5.000"))
        self.assertEqual(ingredient.allocations, [])
        self.assertFalse(ingredient.rescued)

    def test_owned_capped_at_required(self):
        suggestion, _ = self._generate([
            {"name": "Onion", "unit": "count", "quantity": 1},
        ])
        ingredient = suggestion.ingredients.get(name="Onion")
        self.assertEqual(ingredient.owned_quantity, Decimal("1.000"))
        self.assertEqual(ingredient.missing_quantity, Decimal("0.000"))
        self.assertEqual(Decimal(ingredient.allocations[0]["quantity"]),
                         Decimal("1.000"))

    def test_unit_mismatch_produces_no_match(self):
        # Household has Flour in grams; a kilogram proposal must not match.
        suggestion, _ = self._generate([
            {"name": "Flour", "unit": "kg", "quantity": 1},
        ])
        ingredient = suggestion.ingredients.get(name="Flour", unit="kg")
        self.assertEqual(ingredient.owned_quantity, Decimal("0.000"))
        self.assertEqual(ingredient.missing_quantity, Decimal("1.000"))

    def test_case_insensitive_name_match_is_normalized(self):
        suggestion, _ = self._generate([
            {"name": "  oNiOn  ", "unit": "count", "quantity": 2},
        ])
        # Stored name is whitespace-normalized (case preserved); matching
        # against lots is case-insensitive.
        ingredient = suggestion.ingredients.get(name="oNiOn")
        self.assertEqual(ingredient.owned_quantity, Decimal("2.000"))
        self.assertEqual(ingredient.missing_quantity, Decimal("0.000"))

    def test_no_date_lot_is_not_rescued(self):
        suggestion, _ = self._generate([
            {"name": "Flour", "unit": "g", "quantity": 100},
        ])
        ingredient = suggestion.ingredients.get(name="Flour")
        self.assertEqual(ingredient.owned_quantity, Decimal("100.000"))
        self.assertFalse(ingredient.rescued)
        self.assertFalse(ingredient.allocations[0]["rescued"])

    def test_zero_balance_lot_is_skipped(self):
        suggestion, _ = self._generate([
            {"name": "Chili", "unit": "count", "quantity": 1},
        ])
        ingredient = suggestion.ingredients.get(name="Chili")
        self.assertEqual(ingredient.owned_quantity, Decimal("0.000"))
        self.assertEqual(ingredient.missing_quantity, Decimal("1.000"))
        self.assertEqual(ingredient.allocations, [])

    def test_fractional_quantities_persisted_and_reconciled_exactly(self):
        # Regression: fractional JSON numbers (0.1/0.2/0.3/1.1) must be
        # accepted and reconciled with their exact decimal values.
        suggestion, _ = self._generate([
            {"name": "Flour", "unit": "g", "quantity": 1.1},
            {"name": "Garlic", "unit": "g", "quantity": 0.2},
        ])
        flour = suggestion.ingredients.get(name="Flour", unit="g")
        self.assertEqual(flour.required_quantity, Decimal("1.1"))
        self.assertEqual(flour.owned_quantity, Decimal("1.1"))
        self.assertEqual(flour.missing_quantity, Decimal("0.000"))
        self.assertEqual(Decimal(flour.allocations[0]["quantity"]),
                         Decimal("1.1"))
        self.assertFalse(flour.rescued)
        garlic = suggestion.ingredients.get(name="Garlic", unit="g")
        self.assertEqual(garlic.required_quantity, Decimal("0.2"))
        self.assertEqual(garlic.owned_quantity, Decimal("0.2"))
        self.assertEqual(garlic.missing_quantity, Decimal("0.000"))
        # 0.2 g is fully taken from the expiring-today lot.
        self.assertEqual(garlic.allocations[0]["lot"],
                         str(self.lot_garlic_soon.pk))
        self.assertTrue(garlic.rescued)

    def test_imprecise_float_quantity_writes_nothing(self):
        with self.assertRaises(AIMalformedOutputError):
            self._generate([
                {"name": "Onion", "unit": "count", "quantity": 0.0001},
            ])
        self.assertEqual(MealSuggestion.objects.count(), 0)
        self.assertEqual(MealIngredient.objects.count(), 0)
        self.assertEqual(InventoryEvent.objects.count(), self.event_count)

    def test_expired_lot_not_matched_unless_confirmed(self):
        suggestion, _ = self._generate([
            {"name": "Kale", "unit": "count", "quantity": 1},
        ])
        ingredient = suggestion.ingredients.get(name="Kale")
        self.assertEqual(ingredient.owned_quantity, Decimal("0.000"))
        self.assertEqual(ingredient.missing_quantity, Decimal("1.000"))

        suggestion, _ = self._generate([
            {"name": "Kale", "unit": "count", "quantity": 1},
        ], include_expired=True)
        ingredient = suggestion.ingredients.get(name="Kale")
        self.assertEqual(ingredient.owned_quantity, Decimal("1.000"))
        self.assertTrue(ingredient.rescued)

    def test_suggestion_and_ingredients_are_persisted(self):
        suggestion, fake = self._generate([
            {"name": "Onion", "unit": "count", "quantity": 3},
            {"name": "garlic", "unit": "g", "quantity": 10},
        ])
        self.assertEqual(suggestion.title, "Garlicky onion stir-fry")
        self.assertEqual(suggestion.servings, 2)
        self.assertEqual(suggestion.time_minutes, 25)
        self.assertEqual(suggestion.steps, ["Chop the onion.",
                                            "Stir-fry with garlic."])
        self.assertEqual(suggestion.substitutions,
                         ["Olive oil instead of butter."])
        self.assertEqual(suggestion.safety_note, "Mind the hot pan.")
        self.assertEqual(suggestion.rationale, "Uses the onions that expire soon.")
        self.assertEqual(suggestion.provider_model, "fake-model")
        self.assertEqual(suggestion.status, MealSuggestion.Status.SUGGESTED)
        self.assertEqual(suggestion.household, self.user.household)
        self.assertEqual(suggestion.ingredients.count(), 2)
        self.assertEqual(suggestion.household, self.user.household)
        garlic = suggestion.ingredients.get(name="garlic")
        # Garlic: 6 (soonest) from the expiring lot + 4 from the no-date lot.
        self.assertEqual(garlic.owned_quantity, Decimal("10.000"))
        self.assertEqual(garlic.missing_quantity, Decimal("0.000"))
        self.assertEqual(garlic.allocations[0]["lot"],
                         str(self.lot_garlic_soon.pk))
        self.assertEqual(garlic.allocations[1]["lot"],
                         str(self.lot_garlic_nodate.pk))

    def test_suggestion_generation_never_mutates_inventory(self):
        self._generate([
            {"name": "Onion", "unit": "count", "quantity": 4},
            {"name": "garlic", "unit": "g", "quantity": 10},
        ])
        self.assertEqual(InventoryEvent.objects.count(), self.event_count)
        self.assertEqual(self.user.household.lots.count(), 7)
        self.assertEqual(lot_balances(self.user), self.balances_before)

    def test_schema_violation_writes_nothing(self):
        with self.assertRaises(AIMalformedOutputError):
            self._generate([
                {"name": "Onion", "unit": "stone", "quantity": 1},
            ])
        self.assertEqual(MealSuggestion.objects.count(), 0)
        self.assertEqual(MealIngredient.objects.count(), 0)
        self.assertEqual(InventoryEvent.objects.count(), self.event_count)


class MealModelTests(TestCase):
    """Proposal immutability and snapshot append-only semantics."""

    def setUp(self):
        self.user = make_user("model_user")

    def _make(self):
        fake = FakeProvider()
        with mock.patch.object(meal_services, "get_provider",
                               return_value=fake):
            return meal_services.generate_suggestion(
                household=self.user.household,
            )

    def test_provider_fields_are_immutable(self):
        suggestion = self._make()
        suggestion.title = "Changed!"
        with self.assertRaises(ValueError):
            suggestion.save()
        # Status is the lifecycle field and remains mutable.
        suggestion.title = "Garlicky onion stir-fry"
        suggestion.status = MealSuggestion.Status.COOKED
        suggestion.save()
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, MealSuggestion.Status.COOKED)

    def test_ingredients_are_immutable_and_undeletable(self):
        suggestion = self._make()
        ingredient = suggestion.ingredients.first()
        with self.assertRaises(ValueError):
            ingredient.name = "X"
            ingredient.save()
        with self.assertRaises(ValueError):
            ingredient.delete()


class CookViewTests(TestCase):
    """Authenticated POST-only CSRF cook action: PRG, exact ledger
    deductions, duplicate safety, rollback errors, cross-household 404,
    and the detail-page cook states."""

    def setUp(self):
        self.user_a = make_user("cook_a")
        self.user_b = make_user("cook_b")
        make_lot(self.user_a, "Onion", 5, "count")
        make_lot(self.user_b, "Basil", 3, "count")

    def _login(self, username):
        assert self.client.login(
            username=username, password="sup3r-s3cr3t-pass"
        )

    def _cookable_suggestion(self, user, *, title="Onion stir-fry"):
        """A SUGGESTED suggestion whose ingredients are all fully owned,
        so the detail page offers the Cook action and confirm_cook can
        succeed end-to-end."""
        fake = FakeProvider(payload=valid_payload(
            title=title,
            ingredients=[{"name": "Onion", "unit": "count", "quantity": 3}],
        ))
        with mock.patch.object(meal_services, "get_provider",
                               return_value=fake):
            return meal_services.generate_suggestion(
                household=user.household,
            )

    @staticmethod
    def _fully_owned_suggestion(suggestion):
        """Flip every ingredient snapshot to owned == required so the meal
        is cookable. MealIngredient.save() refuses ORM updates, so the
        snapshot is rewritten via raw SQL (the same surface a tampering
        attacker would use)."""
        from django.db import connection

        table = MealIngredient._meta.db_table
        for ingredient in suggestion.ingredients.all():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {table} SET owned_quantity = ?, "
                    "missing_quantity = ? WHERE id = ?",
                    [str(ingredient.required_quantity), "0",
                     str(ingredient.pk)],
                )
        suggestion.refresh_from_db()
        return suggestion

    # -- auth + CSRF + method ---------------------------------------------------

    def test_cook_requires_auth_with_next(self):
        response = self.client.post(
            reverse("inventory:meal_cook", args=[self._cookable_suggestion(self.user_a).pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse(LOGIN), response["Location"])

    def test_cook_get_requires_auth_with_next(self):
        suggestion = self._cookable_suggestion(self.user_a)
        response = self.client.get(
            reverse("inventory:meal_cook", args=[suggestion.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse(LOGIN), response["Location"])

    def test_cook_csrf_rejected_no_deduction(self):
        from django.test import Client as TestClient

        suggestion = self._fully_owned_suggestion(
            self._cookable_suggestion(self.user_a)
        )
        strict = TestClient(enforce_csrf_checks=True)
        assert strict.login(username="cook_a", password="sup3r-s3cr3t-pass")
        response = strict.post(
            reverse("inventory:meal_cook", args=[suggestion.pk])
        )
        self.assertEqual(response.status_code, 403)
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, MealSuggestion.Status.SUGGESTED)
        self.assertEqual(
            InventoryEvent.objects.filter(
                event_type=InventoryEvent.EventType.CONSUME
            ).count(),
            0,
        )

    def test_cook_is_post_only_get_falls_back_to_detail(self):
        self._login("cook_a")
        suggestion = self._fully_owned_suggestion(
            self._cookable_suggestion(self.user_a)
        )
        response = self.client.get(
            reverse("inventory:meal_cook", args=[suggestion.pk]),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain[0][0],
                         reverse(DETAIL, args=[suggestion.pk]))
        self.assertEqual(
            suggestion.status, MealSuggestion.Status.SUGGESTED
        )
        self.assertEqual(
            InventoryEvent.objects.filter(
                event_type=InventoryEvent.EventType.CONSUME
            ).count(),
            0,
        )

    # -- success + PRG + exact ledger deductions --------------------------------

    def test_cook_success_is_prg_with_exact_deduction(self):
        self._login("cook_a")
        suggestion = self._fully_owned_suggestion(
            self._cookable_suggestion(self.user_a)
        )
        lot = self.user_a.household.lots.get()
        response = self.client.post(
            reverse("inventory:meal_cook", args=[suggestion.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"],
                         reverse(DETAIL, args=[suggestion.pk]))
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, MealSuggestion.Status.COOKED)
        self.assertEqual(services.lot_balance(lot), Decimal("2"))
        consumes = InventoryEvent.objects.filter(
            event_type=InventoryEvent.EventType.CONSUME
        )
        self.assertEqual(consumes.count(), 1)
        self.assertEqual(consumes.get().quantity, Decimal("-3"))
        # Cooked state + recorded time on the detail page.
        detail = self.client.get(reverse(DETAIL, args=[suggestion.pk]))
        content = detail.content.decode("utf-8")
        self.assertIn("Cooked on", content)
        self.assertIn("status-cooked", content)
        self.assertNotIn("Cook this meal", content)

    def test_cook_success_shows_message_and_time_followed(self):
        self._login("cook_a")
        suggestion = self._fully_owned_suggestion(
            self._cookable_suggestion(self.user_a)
        )
        response = self.client.post(
            reverse("inventory:meal_cook", args=[suggestion.pk]), follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.redirect_chain), 1)
        self.assertEqual(response.redirect_chain[0][0],
                         reverse(DETAIL, args=[suggestion.pk]))
        content = response.content.decode("utf-8")
        self.assertIn("marked as cooked", content)
        self.assertIn("Cooked on", content)

    # -- duplicate: no second deduction ----------------------------------------

    def test_duplicate_cook_post_does_not_deduct_twice(self):
        self._login("cook_a")
        suggestion = self._fully_owned_suggestion(
            self._cookable_suggestion(self.user_a)
        )
        lot = self.user_a.household.lots.get()
        url = reverse("inventory:meal_cook", args=[suggestion.pk])
        first = self.client.post(url)
        self.assertEqual(first.status_code, 302)
        balance_after_first = services.lot_balance(lot)
        second = self.client.post(url, follow=True)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(services.lot_balance(lot), balance_after_first)
        self.assertEqual(
            InventoryEvent.objects.filter(
                event_type=InventoryEvent.EventType.CONSUME
            ).count(),
            1,
        )
        self.assertEqual(
            MealEvent.objects.filter(suggestion=suggestion).count(), 1
        )
        content = second.content.decode("utf-8")
        self.assertIn("Cook not confirmed", content)
        self.assertIn("already been cooked", content)

    # -- recoverable failure: rollback + useful feedback ------------------------

    def test_recoverable_service_error_renders_feedback_no_partial_writes(self):
        """A recoverable InventoryServiceError from confirm_cook must re-render
        the detail page with a user-safe message and zero partial writes."""
        self._login("cook_a")
        suggestion = self._fully_owned_suggestion(
            self._cookable_suggestion(self.user_a)
        )
        lot = self.user_a.household.lots.get()

        def failing_confirm_cook(*args, **kwargs):
            del args, kwargs
            raise exceptions.InsufficientStock(
                "lot exploded before the write"
            )

        with mock.patch.object(services, "confirm_cook", failing_confirm_cook):
            response = self.client.post(
                reverse("inventory:meal_cook", args=[suggestion.pk])
            )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Cook not confirmed", content)
        self.assertIn("lot exploded before the write", content)
        # No partial writes: suggestion unchanged, ledger untouched.
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, MealSuggestion.Status.SUGGESTED)
        self.assertEqual(services.lot_balance(lot), Decimal("5"))
        self.assertEqual(
            InventoryEvent.objects.filter(
                event_type=InventoryEvent.EventType.CONSUME
            ).count(),
            0,
        )

    # -- blocked / missing-ingredient state --------------------------------------

    def test_blocked_state_shows_plain_language(self):
        self._login("cook_a")
        # Missing Garlic entirely: suggestion is not cookable.
        fake = FakeProvider(payload=valid_payload(
            ingredients=[{"name": "Garlic", "unit": "g", "quantity": 10}],
        ))
        with mock.patch.object(meal_services, "get_provider",
                               return_value=fake):
            suggestion = meal_services.generate_suggestion(
                household=self.user_a.household,
            )
        response = self.client.get(reverse(DETAIL, args=[suggestion.pk]))
        content = response.content.decode("utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Cook this meal", content)
        self.assertIn("can’t be cooked yet", content)
        self.assertIn("cook-state-blocked", content)
        # POSTing the cook action must fail closed with the missing message.
        post = self.client.post(
            reverse("inventory:meal_cook", args=[suggestion.pk]), follow=True
        )
        post_content = post.content.decode("utf-8")
        self.assertIn("Cook not confirmed", post_content)
        self.assertIn("Garlic", post_content)
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, MealSuggestion.Status.SUGGESTED)
        # Two lots exist for user_a (Onion + Basil setup), so the expected
        # ledger has exactly two ADD events and zero CONSUME events.
        self.assertEqual(
            InventoryEvent.objects.filter(
                event_type=InventoryEvent.EventType.CONSUME
            ).count(),
            0,
        )

    def test_rejected_state_rendered(self):
        self._login("cook_a")
        suggestion = self._fully_owned_suggestion(
            self._cookable_suggestion(self.user_a)
        )
        suggestion.status = MealSuggestion.Status.REJECTED
        suggestion.save(update_fields=["status"])
        response = self.client.get(reverse(DETAIL, args=[suggestion.pk]))
        content = response.content.decode("utf-8")
        self.assertNotIn("Cook this meal", content)
        self.assertIn("was rejected and can’t be cooked", content)
        self.assertIn("cook-state-rejected", content)
        post = self.client.post(
            reverse("inventory:meal_cook", args=[suggestion.pk]), follow=True
        )
        self.assertIn("Cook not confirmed", post.content.decode("utf-8"))

    # -- cross-household isolation -------------------------------------------------

    def test_cross_household_cook_get_and_post_are_404(self):
        self._login("cook_a")
        suggestion = self._fully_owned_suggestion(
            self._cookable_suggestion(self.user_a)
        )
        lot = self.user_a.household.lots.get()
        self.client.logout()
        self._login("cook_b")
        cook_url = reverse("inventory:meal_cook", args=[suggestion.pk])
        self.assertEqual(self.client.get(cook_url).status_code, 404)
        response = self.client.post(cook_url, follow=True)
        self.assertEqual(response.status_code, 404)
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, MealSuggestion.Status.SUGGESTED)
        self.assertEqual(services.lot_balance(lot), Decimal("5"))
        self.assertEqual(
            MealEvent.objects.filter(suggestion=suggestion).count(), 0
        )

    def test_unknown_cook_pk_is_404(self):
        import uuid

        self._login("cook_a")
        cook_url = reverse("inventory:meal_cook", args=[uuid.uuid4()])
        self.assertEqual(self.client.get(cook_url).status_code, 404)
        self.assertEqual(
            self.client.post(cook_url, follow=True).status_code, 404
        )

    # -- narrow-width / accessible markup ------------------------------------------

    def test_cook_form_markup_is_accessible_and_narrow_safe(self):
        self._login("cook_a")
        suggestion = self._fully_owned_suggestion(
            self._cookable_suggestion(self.user_a)
        )
        content = self.client.get(
            reverse(DETAIL, args=[suggestion.pk])
        ).content.decode("utf-8")
        # Semantic form + labeled button.
        self.assertIn('<form method="post"', content)
        self.assertIn(reverse("inventory:meal_cook", args=[suggestion.pk]),
                      content)
        self.assertIn('type="submit"', content)
        self.assertIn("Cook this meal", content)
        # The button uses the shared .btn class, which has no fixed width
        # wider than its content; min-width on .cook-button is below the
        # 390px viewport.
        css = (
            Path(__file__).resolve().parents[1]
            / "static" / "inventory" / "styles.css"
        ).read_text(encoding="utf-8")
        self.assertIn(".cook-button", css)
        self.assertIn("min-width: 11rem", css)
        self.assertIn(".cook-state-cooked", css)
        self.assertIn(".cook-state-blocked", css)


class ViewFlowTests(TestCase):
    """Auth, CSRF, PRG, result rendering, history, cross-household isolation."""

    def setUp(self):
        self.user_a = make_user("flow_a")
        self.user_b = make_user("flow_b")
        make_lot(self.user_a, "Onion", 5, "count",
                 expires_on=timezone.localdate())
        make_lot(self.user_b, "Basil", 3, "count")

    def _login(self, username):
        assert self.client.login(
            username=username, password="sup3r-s3cr3t-pass"
        )

    def test_pages_require_auth_with_next(self):
        for name in (SUGGEST, HISTORY):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse(LOGIN), response["Location"])

    def test_anonymous_post_creates_nothing(self):
        response = self.client.post(reverse(SUGGEST), FORM_DATA)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse(LOGIN), response["Location"])
        self.assertEqual(MealSuggestion.objects.count(), 0)

    def test_csrf_rejected_and_no_rows(self):
        from django.test import Client as TestClient

        strict = TestClient(enforce_csrf_checks=True)
        assert strict.login(username="flow_a", password="sup3r-s3cr3t-pass")
        response = strict.post(reverse(SUGGEST), FORM_DATA)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(MealSuggestion.objects.count(), 0)
        self.assertEqual(MealIngredient.objects.count(), 0)

    def test_success_is_prg_to_result(self):
        self._login("flow_a")
        fake = FakeProvider()
        with mock.patch.object(meal_services, "get_provider",
                               return_value=fake):
            response = self.client.post(reverse(SUGGEST), FORM_DATA,
                                        follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.redirect_chain), 1)
        suggestion = MealSuggestion.objects.get()
        self.assertEqual(
            response.redirect_chain[0][0],
            reverse(DETAIL, args=[suggestion.pk]),
        )
        content = response.content.decode("utf-8")
        # Result page renders all required pieces.
        self.assertIn("Garlicky onion stir-fry", content)
        self.assertIn("Servings", content)
        self.assertIn("2", content)
        self.assertIn("25 min", content)
        self.assertIn("Chop the onion.", content)
        self.assertIn("Stir-fry with garlic.", content)
        self.assertIn("Olive oil instead of butter.", content)
        self.assertIn("Mind the hot pan.", content)
        self.assertIn("Uses the onions that expire soon.", content)
        self.assertIn("fake-model", content)
        self.assertIn("rescues expiring stock", content)  # onion expires today
        self.assertIn(timezone.localdate().isoformat(), content)
        self.assertIn("Meal ingredient quantities", content)
        self.assertIn("Why this meal", content)
        self.assertIn("Suggested", content)

    def test_result_page_shows_owned_and_missing(self):
        self._login("flow_a")
        # Garlic is not in the pantry: fully missing.
        fake = FakeProvider(payload=valid_payload(ingredients=[
            {"name": "Onion", "unit": "count", "quantity": 4},
            {"name": "Garlic", "unit": "g", "quantity": 10},
        ]))
        with mock.patch.object(meal_services, "get_provider",
                               return_value=fake):
            suggestion = meal_services.generate_suggestion(
                household=self.user_a.household,
            )
        response = self.client.get(reverse(DETAIL, args=[suggestion.pk]))
        content = response.content.decode("utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertIn("You have", content)
        self.assertIn("4.000 count", content)  # owned onions
        self.assertIn("10.000 g", content)     # missing garlic quantity
        self.assertIn("Suggested", content)

    def test_provider_failure_rerenders_form_with_banner(self):
        self._login("flow_a")
        fake = FakeProvider(error=AIProviderError("upstream is down"))
        with mock.patch.object(meal_services, "get_provider",
                               return_value=fake):
            response = self.client.post(reverse(SUGGEST), FORM_DATA)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Could not generate a meal", content)
        self.assertIn("upstream is down", content)
        # Form still present and usable; no rows created.
        self.assertIn("id_servings", content)
        self.assertIn("checkbox-label", content)
        self.assertIn("id_include_expired", content)
        self.assertEqual(MealSuggestion.objects.count(), 0)

    def test_fractional_quantity_provider_path_completes_prg(self):
        # Regression: a provider JSON number like 0.1 was rejected as "not
        # exact to 3 decimal places", so a valid completion with a numeric
        # fractional ingredient retried forever. The real provider path
        # (HTTP + default json.loads float decoding) must complete the PRG
        # flow and persist the exact decimal value.
        self._login("flow_a")
        payload = valid_payload(ingredients=[
            {"name": "Onion", "unit": "count", "quantity": 3},
            {"name": "Flour", "unit": "g", "quantity": 0.1},
        ])
        with mock.patch.dict(os.environ, {
            "AI_BASE_URL": "http://ai.test", "AI_MODEL": "test-model",
            "AI_API_KEY": "", "AI_TIMEOUT": "",
        }):
            with mock.patch.object(
                    openai_module.urllib.request, "urlopen",
                    return_value=FakeHTTPResponse(
                        chat_response(json.dumps(payload)))):
                response = self.client.post(reverse(SUGGEST), FORM_DATA,
                                            follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.redirect_chain), 1)
        suggestion = MealSuggestion.objects.get()
        self.assertEqual(response.redirect_chain[0][0],
                         reverse(DETAIL, args=[suggestion.pk]))
        content = response.content.decode("utf-8")
        self.assertNotIn("Could not generate a meal", content)
        self.assertIn("0.100 g", content)  # missing Flour quantity
        ingredient = suggestion.ingredients.get(name="Flour", unit="g")
        self.assertEqual(ingredient.required_quantity, Decimal("0.1"))
        self.assertEqual(ingredient.owned_quantity, Decimal("0.000"))
        self.assertEqual(ingredient.missing_quantity, Decimal("0.1"))

    def test_history_lists_own_suggestions(self):
        self._login("flow_a")
        fake = FakeProvider()
        with mock.patch.object(meal_services, "get_provider",
                               return_value=fake):
            suggestion_a1 = meal_services.generate_suggestion(
                household=self.user_a.household,
            )
            fake.payload = valid_payload(title="Second meal")
            suggestion_a2 = meal_services.generate_suggestion(
                household=self.user_a.household,
            )
        response = self.client.get(reverse(HISTORY))
        content = response.content.decode("utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Garlicky onion stir-fry", content)
        self.assertIn("Second meal", content)
        self.assertIn(reverse(DETAIL, args=[suggestion_a1.pk]), content)
        self.assertIn("Meal suggestion history", content)

    def test_history_empty_state(self):
        self._login("flow_b")
        response = self.client.get(reverse(HISTORY))
        content = response.content.decode("utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertIn("No meal suggestions yet", content)

    def test_cross_household_detail_is_404(self):
        self._login("flow_a")
        fake = FakeProvider()
        with mock.patch.object(meal_services, "get_provider",
                               return_value=fake):
            suggestion_a = meal_services.generate_suggestion(
                household=self.user_a.household,
            )
        self.client.logout()
        self._login("flow_b")
        response = self.client.get(reverse(DETAIL, args=[suggestion_a.pk]))
        self.assertEqual(response.status_code, 404)

    def test_cross_household_post_cannot_generate_or_read(self):
        # B's form must snapshot only B's lots, and B's history must not
        # show A's suggestion.
        self._login("flow_a")
        fake_a = FakeProvider()
        with mock.patch.object(meal_services, "get_provider",
                               return_value=fake_a):
            suggestion_a = meal_services.generate_suggestion(
                household=self.user_a.household,
            )
        self.client.logout()
        self._login("flow_b")
        fake_b = FakeProvider(payload=valid_payload(
            title="Basil toast",
            ingredients=[{"name": "Basil", "unit": "count", "quantity": 1}],
        ))
        with mock.patch.object(meal_services, "get_provider",
                               return_value=fake_b):
            response = self.client.post(reverse(SUGGEST), FORM_DATA,
                                        follow=True)
        self.assertEqual(response.status_code, 200)
        (call,) = fake_b.calls
        products = [item["product"] for item in call["snapshot"]]
        self.assertEqual(products, ["Basil"])
        suggestion_b = MealSuggestion.objects.get(
            household=self.user_b.household
        )
        self.assertEqual(suggestion_b.ingredients.count(), 1)
        history = self.client.get(reverse(HISTORY))
        content = history.content.decode("utf-8")
        self.assertNotIn(suggestion_a.title, content)
        self.assertIn("Basil toast", content)

    def test_unknown_pk_is_404(self):
        import uuid

        self._login("flow_a")
        response = self.client.get(
            reverse(DETAIL, args=[uuid.uuid4()])
        )
        self.assertEqual(response.status_code, 404)

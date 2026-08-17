"""Authenticated meal-suggestion views (form, result, history).

All reads are scoped to ``request.user.household``; foreign-household
suggestions 404 on GET and POST. The generate endpoint follows the PRG
pattern: success redirects to the result page; provider failures re-render
the form with a recoverable, user-safe error banner and no partial data.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import FormView, TemplateView

from . import meal_services, services
from .ai import AIProviderError
from .exceptions import InventoryServiceError
from .forms import MealSuggestionForm
from .models import MealSuggestion, StockLot
from .views import current_household


def owned_suggestion(user, pk):
    """Fetch a suggestion only if it belongs to the user's household."""
    return get_object_or_404(
        MealSuggestion, pk=pk, household=current_household(user)
    )


def cook_state(suggestion):
    """Render-facing cook state for a household-owned suggestion.

    Returns ``(state, cook_event)`` where ``state`` is one of
    ``"ready"`` (SUGGESTED, nothing missing — the Cook action may render),
    ``"blocked"`` (SUGGESTED but an ingredient is missing), ``"cooked"``
    (with the cook record) or ``"rejected"``.
    """
    if suggestion.status == MealSuggestion.Status.COOKED:
        try:
            return "cooked", suggestion.meal_event
        except ObjectDoesNotExist:
            # A COOKED status without the related event is inconsistent
            # state; render the cooked state without a timestamp.
            return "cooked", None
    if suggestion.status == MealSuggestion.Status.REJECTED:
        return "rejected", None
    if suggestion.status != MealSuggestion.Status.SUGGESTED:
        return "blocked", None
    missing = [
        ingredient for ingredient in suggestion.ingredients.all()
        if ingredient.missing_quantity > 0
    ]
    return ("blocked" if missing else "ready"), None


class SuggestionFormView(LoginRequiredMixin, FormView):
    """POST a set of meal constraints; PRG to the result on success."""

    template_name = "inventory/meals/form.html"
    form_class = MealSuggestionForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["household"] = current_household(self.request.user)
        context.setdefault("ai_error", None)
        return context

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        if form.is_valid():
            data = form.cleaned_data
            try:
                suggestion = meal_services.generate_suggestion(
                    household=current_household(request.user),
                    servings=data["servings"],
                    max_minutes=data["max_minutes"],
                    dietary_exclusions=data["dietary_exclusions"],
                    preference=data["preference"],
                    include_expired=data["include_expired"],
                )
            except AIProviderError as exc:
                # Recoverable failure: re-render the form with the
                # user-safe message; no redirect, no partial data.
                context = self.get_context_data(form=form)
                context["ai_error"] = exc.message
                return render(request, self.template_name, context)
            messages.success(request, f"Suggested “{suggestion.title}”.")
            return redirect("inventory:meal_detail", pk=suggestion.pk)
        return self.render_to_response(
            self.get_context_data(form=form)
        )


@login_required
def suggestion_detail(request, pk):
    """The result page: full proposal plus the reconciliation snapshot."""
    suggestion = owned_suggestion(request.user, pk)
    ingredients = list(suggestion.ingredients.all())
    rescued_ingredients = [i for i in ingredients if i.rescued]
    lot_ids = {
        allocation["lot"]
        for ingredient in ingredients
        for allocation in (ingredient.allocations or [])
    }
    lots = {
        str(lot.pk): lot
        for lot in StockLot.objects.filter(
            pk__in=lot_ids, household=current_household(request.user)
        )
    }
    rescued_allocations = []
    for ingredient in rescued_ingredients:
        for allocation in ingredient.allocations or []:
            if not allocation.get("rescued"):
                continue
            lot = lots.get(str(allocation.get("lot")))
            if lot is None or lot.expires_on is None:
                continue
            rescued_allocations.append(
                {
                    "ingredient_name": ingredient.name,
                    "unit": ingredient.unit,
                    "quantity": allocation.get("quantity"),
                    "expires_on": lot.expires_on,
                }
            )
    state, cook_event = cook_state(suggestion)
    context = {
        "household": current_household(request.user),
        "suggestion": suggestion,
        "ingredients": ingredients,
        "rescued_ingredients": rescued_ingredients,
        "lots": lots,
        "rescued_allocations": rescued_allocations,
        "cook_state": state,
        "cook_event": cook_event,
    }
    return render(request, "inventory/meals/detail.html", context)


class CookSuggestionView(LoginRequiredMixin, View):
    """POST-only, CSRF-protected cook confirmation for one suggestion.

    The view owns exactly one concern: household-scoped lookup (foreign /
    unknown pks 404 on both GET and POST) and PRG. All deduction, locking,
    exactly-once and rollback semantics live in
    ``services.confirm_cook``; every recoverable failure re-renders the
    detail page with a user-safe message and no partial writes. Django's
    CSRF middleware covers the POST (the view is a plain :class:`View` with
    no CSRF bypass).
    """

    http_method_names = ["post", "get", "head", "options"]

    def get(self, request, *args, **kwargs):
        """GET is not a valid cook method.

        Foreign / unknown pks 404 first (household-scoped lookup), and an
        owned suggestion gets a 405 with ``Allow: POST`` so clients learn
        the correct method.
        """
        from django.http import HttpResponseNotAllowed
        owned_suggestion(request.user, self.kwargs["pk"])
        return HttpResponseNotAllowed(
            ["POST"],
        )

    def post(self, request, *args, **kwargs):
        pk = self.kwargs["pk"]
        suggestion = owned_suggestion(request.user, pk)
        try:
            services.confirm_cook(
                household=current_household(request.user),
                suggestion=suggestion,
            )
        except InventoryServiceError as exc:
            # Recoverable service failure: nothing was written (the service
            # rolled back), so re-render the detail page with the message.
            messages.error(request, f"Cook not confirmed: {exc}")
            return render(
                request,
                "inventory/meals/detail.html",
                self._context(request, suggestion),
            )
        messages.success(request, f"“{suggestion.title}” marked as cooked.")
        return redirect("inventory:meal_detail", pk=pk)

    def _context(self, request, suggestion):
        ingredients = list(suggestion.ingredients.all())
        rescued_ingredients = [i for i in ingredients if i.rescued]
        lot_ids = {
            allocation["lot"]
            for ingredient in ingredients
            for allocation in (ingredient.allocations or [])
        }
        lots = {
            str(lot.pk): lot
            for lot in StockLot.objects.filter(
                pk__in=lot_ids, household=current_household(request.user)
            )
        }
        rescued_allocations = []
        for ingredient in rescued_ingredients:
            for allocation in ingredient.allocations or []:
                if not allocation.get("rescued"):
                    continue
                lot = lots.get(str(allocation.get("lot")))
                if lot is None or lot.expires_on is None:
                    continue
                rescued_allocations.append(
                    {
                        "ingredient_name": ingredient.name,
                        "unit": ingredient.unit,
                        "quantity": allocation.get("quantity"),
                        "expires_on": lot.expires_on,
                    }
                )
        state, cook_event = cook_state(suggestion)
        return {
            "household": current_household(request.user),
            "suggestion": suggestion,
            "ingredients": ingredients,
            "rescued_ingredients": rescued_ingredients,
            "lots": lots,
            "rescued_allocations": rescued_allocations,
            "cook_state": state,
            "cook_event": cook_event,
        }


class SuggestionHistoryView(LoginRequiredMixin, TemplateView):
    """This household's suggestion history, newest first."""

    template_name = "inventory/meals/history.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["household"] = current_household(self.request.user)
        context["suggestions"] = MealSuggestion.objects.filter(
            household=current_household(self.request.user)
        ).prefetch_related("ingredients")
        return context

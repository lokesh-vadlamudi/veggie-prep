"""Authenticated meal-suggestion views (form, result, history).

All reads are scoped to ``request.user.household``; foreign-household
suggestions 404 on GET and POST. The generate endpoint follows the PRG
pattern: success redirects to the result page; provider failures re-render
the form with a recoverable, user-safe error banner and no partial data.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import FormView, TemplateView

from . import meal_services
from .ai import AIProviderError
from .forms import MealSuggestionForm
from .models import MealSuggestion, StockLot
from .views import current_household


def owned_suggestion(user, pk):
    """Fetch a suggestion only if it belongs to the user's household."""
    return get_object_or_404(
        MealSuggestion, pk=pk, household=current_household(user)
    )


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
    context = {
        "household": current_household(request.user),
        "suggestion": suggestion,
        "ingredients": ingredients,
        "rescued_ingredients": rescued_ingredients,
        "lots": lots,
        "rescued_allocations": rescued_allocations,
    }
    return render(request, "inventory/meals/detail.html", context)


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

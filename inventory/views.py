"""Server-rendered, authenticated inventory workflow views.

Every view scopes all reads and writes to ``request.user.household`` (each
user has exactly one household, maintained by the user ``post_save`` signal).
Foreign-household objects are invisible here: they 404 on both GET and POST.
All inventory writes delegate to :mod:`inventory.services`, which owns the
domain rules and transactional guarantees; views only map service errors
back onto form fields.
"""

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import FormView, TemplateView

from . import services
from .exceptions import (
    InvalidAdjustment,
    InvalidQuantity,
    InventoryServiceError,
    InsufficientStock,
    UnitMismatch,
)
from .forms import AddStockForm, CorrectionForm, LotMutationForm
from .models import StockLot
from .services import normalize_product_name  # noqa: F401  (re-exported)


def current_household(user):
    """The logged-in user's household (exactly one, guaranteed by signal)."""
    return user.household


def owned_lot(user, lot_pk):
    """Fetch a lot only if it belongs to the user's household, else 404."""
    return get_object_or_404(StockLot, pk=lot_pk, household=current_household(user))


def _expiry_groups(lot_entries):
    """Group lot entries by expiry bucket relative to today.

    ``lot_entries`` is a sequence of ``{"lot": lot, "balance": balance}``
    dicts (positive balance only). Buckets: ``expired`` (before today),
    ``today``, ``next2`` (today+1 or today+2), ``later`` (after today+2 or
    no expiry date). Dates are compared against ``django.utils.timezone.localdate``.
    """
    today = timezone.localdate()
    groups = {"expired": [], "today": [], "next2": [], "later": []}
    for entry in lot_entries:
        expires_on = entry["lot"].expires_on
        if expires_on is None:
            bucket = "later"
        elif expires_on < today:
            bucket = "expired"
        elif expires_on == today:
            bucket = "today"
        elif expires_on <= today + timedelta(days=2):
            bucket = "next2"
        else:
            bucket = "later"
        groups[bucket].append(entry)
    return groups


class DashboardView(LoginRequiredMixin, TemplateView):
    """Responsive dashboard: fast-add form + positive-balance lots grouped by expiry."""

    template_name = "inventory/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        household = current_household(self.request.user)
        lot_entries = []
        for lot in household.lots.all().order_by("created_at", "id"):
            balance = services.lot_balance(lot)
            if balance > 0:
                lot_entries.append({"lot": lot, "balance": balance})
        context.update(
            {
                "household": household,
                "lots": lot_entries,
                "groups": _expiry_groups(lot_entries),
                "add_form": AddStockForm(),
                "total_lots": len(lot_entries),
            }
        )
        return context


class AddStockView(LoginRequiredMixin, FormView):
    """Record a new lot. PRG on success; on failure re-render with errors."""

    template_name = "inventory/add.html"
    form_class = AddStockForm
    success_url = reverse_lazy("inventory:dashboard")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["household"] = current_household(self.request.user)
        return context

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        if form.is_valid():
            household = current_household(request.user)
            data = form.cleaned_data
            try:
                with transaction.atomic():
                    product = services.resolve_product(
                        household=household,
                        raw_name=data["product_name"],
                        unit=data["unit"],
                    )
                    services.add_stock(
                        household=household,
                        product=product,
                        quantity=data["quantity"],
                        unit=data["unit"],
                        location=data["location"],
                        purchased_at=data.get("purchased_at"),
                        expires_on=data.get("expires_on"),
                        note=data.get("note") or "",
                    )
            except UnitMismatch as exc:
                form.add_error("unit", str(exc))
            except InvalidQuantity as exc:
                form.add_error("quantity", str(exc))
            except InventoryServiceError as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(
                    request,
                    f"Added {data['quantity']} {data['unit']} {product.name} "
                    f"to {data['location'].replace('_', ' ')}.",
                )
                return redirect(self.get_success_url())
        return self.render_to_response(self.get_context_data(form=form))


@login_required
def lot_detail(request, pk):
    """Lot detail: ledger-derived balance, metadata, chronological audit history."""
    lot = owned_lot(request.user, pk)
    events = lot.events.all().order_by("created_at", "id")
    context = {
        "household": current_household(request.user),
        "lot": lot,
        "balance": services.lot_balance(lot),
        "events": events,
        "consume_form": LotMutationForm(),
        "discard_form": LotMutationForm(),
        "correct_form": CorrectionForm(),
        "active_action": None,
    }
    return render(request, "inventory/lot_detail.html", context)


class _LotMutationView(LoginRequiredMixin, View):
    """Shared plumbing for the consume / discard / correct POST endpoints."""

    action = ""
    form_class = None

    def _context(self, form=None, action=None):
        lot = owned_lot(self.request.user, self.kwargs["pk"])
        context = {
            "household": current_household(self.request.user),
            "lot": lot,
            "balance": services.lot_balance(lot),
            "events": lot.events.all().order_by("created_at", "id"),
            "consume_form": LotMutationForm(),
            "discard_form": LotMutationForm(),
            "correct_form": CorrectionForm(),
            "active_action": action or self.action,
        }
        if form is not None:
            context[f"{self.action}_form"] = form
        return context

    def get(self, request, *args, **kwargs):
        # GET falls back to the detail page; mutations are POST-only. The
        # ownership check keeps foreign-household GETs 404, not 302-to-404.
        owned_lot(request.user, self.kwargs["pk"])
        return redirect("inventory:lot_detail", pk=self.kwargs["pk"])

    def post(self, request, *args, **kwargs):
        lot = owned_lot(request.user, self.kwargs["pk"])
        form = self.form_class(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                self.perform_action(request.user, lot, data)
            except (
                InvalidQuantity,
                InvalidAdjustment,
                InsufficientStock,
                InventoryServiceError,
            ) as exc:
                form.add_error(self.field_for_exception(exc), str(exc))
            else:
                messages.success(request, self.success_message(lot, data))
                return redirect("inventory:lot_detail", pk=lot.pk)
        return render(
            request, "inventory/lot_detail.html", self._context(form=form)
        )

    def field_for_exception(self, exc):
        """Form field to display ``exc`` on; ``None`` renders it non-field."""
        if isinstance(exc, InvalidQuantity):
            return "quantity"
        return None

    def perform_action(self, user, lot, data):
        raise NotImplementedError

    def success_message(self, lot, data):
        raise NotImplementedError


class ConsumeView(_LotMutationView):
    action = "consume"
    form_class = LotMutationForm

    def perform_action(self, user, lot, data):
        services.consume_stock(
            household=current_household(user),
            lot=lot,
            quantity=data["quantity"],
            unit=lot.unit,
            note=data.get("note") or "",
        )

    def success_message(self, lot, data):
        return f"Consumed {data['quantity']} {lot.unit} {lot.product.name}."


class DiscardView(_LotMutationView):
    action = "discard"
    form_class = LotMutationForm

    def perform_action(self, user, lot, data):
        services.discard_stock(
            household=current_household(user),
            lot=lot,
            quantity=data["quantity"],
            unit=lot.unit,
            note=data.get("note") or "",
        )

    def success_message(self, lot, data):
        return f"Discarded {data['quantity']} {lot.unit} {lot.product.name}."


class CorrectView(_LotMutationView):
    """Correction: observed balance + required reason → signed ADJUST delta.

    The balance pre-read and delta derivation happen inside
    :func:`inventory.services.set_lot_balance` *after* the lot row lock, so
    a concurrent mutation can never leave the lot off the observed balance.
    """

    action = "correct"
    form_class = CorrectionForm

    def field_for_exception(self, exc):
        if isinstance(exc, InvalidQuantity):
            return "observed_balance"
        return super().field_for_exception(exc)

    def perform_action(self, user, lot, data):
        services.set_lot_balance(
            household=current_household(user),
            lot=lot,
            observed_balance=data["observed_balance"],
            note=data["reason"],
        )

    def success_message(self, lot, data):
        return f"Corrected {lot.product.name} to {data['observed_balance']} {lot.unit}."

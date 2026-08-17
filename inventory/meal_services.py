"""Meal-suggestion generation: snapshot, provider call, reconciliation,
and the single atomic persist.

Flow
----
1. ``build_inventory_snapshot`` derives a bounded, structured view of the
   household's positive-balance lots (never stored, never sent to the UI
   raw). Expired lots are excluded unless the user explicitly confirmed
   them; lots expiring today/+1/+2 are marked ``expiry_soon`` so the
   provider prioritizes their use.
2. The provider is called with the snapshot plus the user's requirements
   (servings, max minutes, exclusions, preference).
3. The provider's JSON is validated and normalized
   (:func:`inventory.ai.validate_proposal`) *before* any database write.
4. Each ingredient is deterministically reconciled against the household's
   lots: exact unit matching, normalized case-insensitive name matching,
   expiry-priority allocation order. This step is read-only.
5. The suggestion and its ingredient snapshots are created in one
   transaction. No inventory event is ever written by this module:
   suggestions never mutate stock.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from . import services
from .ai import get_provider, validate_proposal
from .models import MealIngredient, MealSuggestion, StockLot

#: Expiry-priority window: lots expiring within this many days.
EXPIRY_PRIORITY_DAYS = 2


def _lot_expiry_rank(lot, today):
    """Deterministic allocation rank: soonest expiring first, no-date last."""
    if lot.expires_on is not None:
        if lot.expires_on <= today + timedelta(days=EXPIRY_PRIORITY_DAYS):
            # Priority band: expired (when explicitly included) first, then
            # today, +1, +2.
            return 0
        return 1
    return 2


def _lot_sort_key(lot, today):
    expires = lot.expires_on if lot.expires_on is not None else date.max
    return (_lot_expiry_rank(lot, today), expires, lot.created_at, lot.pk)


def build_inventory_snapshot(household, *, include_expired: bool = False) -> list:
    """Structured snapshot of the household's positive-balance lots.

    * Lots with a derived balance of zero or less are omitted.
    * Expired lots are omitted unless ``include_expired`` is True.
    * Lots expiring today/+1/+2 are flagged ``"expiry_soon"`` (rescuable);
      explicitly included expired lots are flagged ``"expired"``; others
      ``"later"``; lots without a date ``"no_date"``.
    * Ordering is deterministic: expiry rank, then expiry date, then
      creation order.

    The snapshot contains only public facts (name, unit, quantity,
    location, expiry date, flag); no secrets and no raw prompts.
    """
    today = timezone.localdate()
    snapshot = []
    lots = list(household.lots.all().order_by("created_at", "id"))
    for lot in sorted(lots, key=lambda l: _lot_sort_key(l, today)):
        balance = services.lot_balance(lot)
        if balance <= 0:
            continue
        if lot.expires_on is not None and lot.expires_on < today:
            if not include_expired:
                continue
            expiry_flag = "expired"
        elif lot.expires_on is not None and lot.expires_on <= today + timedelta(
            days=EXPIRY_PRIORITY_DAYS
        ):
            expiry_flag = "expiry_soon"
        elif lot.expires_on is None:
            expiry_flag = "no_date"
        else:
            expiry_flag = "later"
        snapshot.append(
            {
                "id": str(lot.pk),
                "product": lot.product.name,
                "unit": lot.unit,
                "available": str(balance),
                "location": lot.location,
                "expires_on": lot.expires_on.isoformat()
                if lot.expires_on
                else None,
                "expiry": expiry_flag,
            }
        )
    return snapshot


def _is_rescuable(lot, today) -> bool:
    """True when the lot is expiring (today/+1/+2) or expired."""
    return lot.expires_on is not None and lot.expires_on <= today + timedelta(
        days=EXPIRY_PRIORITY_DAYS
    )


def _reconcile(household, name, unit, required, today, *, include_expired):
    """Allocate ``required`` from the household's matching lots.

    Matching is exact on unit and case-insensitive (normalized) on the
    product name. Lots the provider was not shown are not matched:
    expired lots are skipped unless ``include_expired`` mirrors the
    snapshot the provider saw. Allocation order is deterministic:
    expiry-priority lots first (earliest expiry first, including
    explicitly included expired lots), then later-dated lots, then
    undated lots; within the same band, lot creation order. Read-only.

    Returns ``(allocations, owned_total, missing, rescued_any)`` where
    ``allocations`` is a list of
    ``{"lot": <uuid str>, "quantity": <decimal str>, "rescued": bool}``.
    """
    candidates = list(
        StockLot.objects.filter(
            household=household,
            product__name__iexact=name,
            unit=unit,
        ).select_related("product")
    )
    if not include_expired:
        candidates = [
            lot for lot in candidates
            if lot.expires_on is None or lot.expires_on >= today
        ]
    allocations = []
    owned = Decimal("0")
    remaining = required
    for lot in sorted(candidates, key=lambda l: _lot_sort_key(l, today)):
        if remaining <= 0:
            break
        balance = services.lot_balance(lot)
        if balance <= 0:
            continue
        take = balance if balance < remaining else remaining
        allocations.append(
            {
                "lot": str(lot.pk),
                "quantity": str(take),
                "rescued": _is_rescuable(lot, today),
            }
        )
        owned += take
        remaining -= take
    missing = remaining if remaining > 0 else Decimal("0")
    rescued_any = any(a["rescued"] for a in allocations)
    return allocations, owned, missing, rescued_any


@transaction.atomic
def generate_suggestion(
    *,
    household,
    servings: int = 2,
    max_minutes: int = 45,
    dietary_exclusions: str = "",
    preference: str = "",
    include_expired: bool = False,
) -> MealSuggestion:
    """Generate, validate, reconcile, and atomically persist a suggestion.

    Raises an :class:`inventory.ai.AIProviderError` subclass (or a
    validator error) on any provider/validity failure; nothing is written
    in that case and no inventory is touched. Raises ``AIMalformedOutputError``
    when the provider output violates the schema (including unsupported
    units and bad quantities).
    """
    snapshot = build_inventory_snapshot(household, include_expired=include_expired)
    provider = get_provider()
    raw = provider.generate(
        snapshot,
        requirements={
            "servings": servings,
            "max_minutes": max_minutes,
            "dietary_exclusions": dietary_exclusions,
            "preference": preference,
            "include_expired": include_expired,
        },
    )
    proposal = validate_proposal(raw, provider_model=provider.model_name)

    today = timezone.localdate()
    suggestion = MealSuggestion.objects.create(
        household=household,
        status=MealSuggestion.Status.SUGGESTED,
        title=proposal.title,
        servings=proposal.servings,
        time_minutes=proposal.time_minutes,
        steps=list(proposal.steps),
        substitutions=list(proposal.substitutions),
        safety_note=proposal.safety_note,
        rationale=proposal.rationale,
        provider_model=provider.model_name,
    )
    for ingredient in proposal.ingredients:
        allocations, owned, missing, rescued = _reconcile(
            household, ingredient.name, ingredient.unit, ingredient.quantity,
            today,
            include_expired=include_expired,
        )
        MealIngredient.objects.create(
            suggestion=suggestion,
            household=household,
            name=ingredient.name,
            unit=ingredient.unit,
            required_quantity=ingredient.quantity,
            owned_quantity=owned,
            missing_quantity=missing,
            rescued=rescued,
            allocations=allocations,
        )
    return suggestion

package com.lokeshvadlamudi.veggieprep.ai

import com.lokeshvadlamudi.veggieprep.data.IndianIngredientCatalog
import com.lokeshvadlamudi.veggieprep.data.MealAllocation
import com.lokeshvadlamudi.veggieprep.data.MealIngredient
import com.lokeshvadlamudi.veggieprep.data.MealProposal
import com.lokeshvadlamudi.veggieprep.data.PantryItem
import java.time.LocalDate

object MealPlanningPolicy {
    fun eligiblePantry(
        pantry: List<PantryItem>,
        today: LocalDate = LocalDate.now(),
    ): List<PantryItem> = pantry
        .filter { item ->
            val expiry = parsedExpiry(item)
            expiry == null || !expiry.isBefore(today)
        }
        .sortedWith(compareBy<PantryItem> { parsedExpiry(it) ?: LocalDate.MAX }.thenBy { it.id })

    fun requiredExpiryItem(
        pantry: List<PantryItem>,
        today: LocalDate = LocalDate.now(),
    ): PantryItem? = eligiblePantry(pantry, today)
        .mapNotNull { item ->
            item.expiresOn
                ?.let { runCatching { LocalDate.parse(it) }.getOrNull() }
                ?.let { expiry -> expiry to item }
        }
        .minWithOrNull(compareBy<Pair<LocalDate, PantryItem>> { it.first }.thenBy { it.second.id })
        ?.second

    fun reconcile(
        meal: MealProposal,
        pantry: List<PantryItem>,
        requiredItem: PantryItem?,
        requestedServings: Int,
        maxMinutes: Int,
        today: LocalDate = LocalDate.now(),
    ): MealProposal {
        require(meal.servings == requestedServings) {
            "The meal suggestion did not honor the requested serving count."
        }
        require(meal.timeMinutes <= maxMinutes) {
            "The meal suggestion exceeded the requested cooking time."
        }

        val eligible = eligiblePantry(pantry, today)
        val remainingByLot = eligible.associate { it.id to it.quantityMilli }.toMutableMap()
        val allocations = mutableListOf<MealAllocation>()
        val missing = mutableListOf<MealIngredient>()

        meal.ingredients.forEach { ingredient ->
            val family = unitFamily(ingredient.unit)
            var remainingBase = toBase(ingredient.quantityMilli, ingredient.unit)
            eligible.asSequence()
                .filter { IndianIngredientCatalog.canonicalKey(it.name) == IndianIngredientCatalog.canonicalKey(ingredient.name) }
                .filter { unitFamily(it.unit) == family }
                .forEach { lot ->
                    if (remainingBase <= 0) return@forEach
                    val available = remainingByLot.getValue(lot.id)
                    if (available <= 0) return@forEach
                    val availableBase = toBase(available, lot.unit)
                    val allocatedBase = minOf(remainingBase, availableBase)
                    val allocatedInLotUnit = fromBase(allocatedBase, lot.unit)
                    if (allocatedInLotUnit <= 0) return@forEach
                    val expiry = parsedExpiry(lot)
                    allocations += MealAllocation(
                        lotId = lot.id,
                        name = lot.name,
                        unit = lot.unit,
                        quantityMilli = allocatedInLotUnit,
                        expiresOn = lot.expiresOn,
                        rescued = expiry != null && !expiry.isAfter(today.plusDays(2)),
                    )
                    remainingByLot[lot.id] = available - allocatedInLotUnit
                    remainingBase -= toBase(allocatedInLotUnit, lot.unit)
                }
            if (remainingBase > 0) {
                missing += ingredient.copy(quantityMilli = fromBaseRoundedUp(remainingBase, ingredient.unit))
            }
        }

        if (requiredItem != null) {
            require(allocations.any { it.lotId == requiredItem.id && it.quantityMilli > 0 }) {
                "The suggestion skipped ${requiredItem.name}, the earliest-expiring pantry item. Try another meal."
            }
        }

        return meal.copy(
            allocations = allocations,
            missingIngredients = missing,
        )
    }

    private fun unitFamily(unit: String): String = when (unit) {
        "g", "kg" -> "mass"
        "ml", "l" -> "volume"
        "count", "each" -> "count"
        else -> unit
    }

    private fun factor(unit: String): Long = when (unit) {
        "kg", "l" -> 1_000L
        else -> 1L
    }

    private fun toBase(quantityMilli: Long, unit: String): Long = Math.multiplyExact(quantityMilli, factor(unit))

    private fun fromBase(quantityBase: Long, unit: String): Long = quantityBase / factor(unit)

    private fun fromBaseRoundedUp(quantityBase: Long, unit: String): Long {
        val factor = factor(unit)
        return (quantityBase + factor - 1) / factor
    }

    private fun parsedExpiry(item: PantryItem): LocalDate? =
        item.expiresOn?.let { runCatching { LocalDate.parse(it) }.getOrNull() }
}

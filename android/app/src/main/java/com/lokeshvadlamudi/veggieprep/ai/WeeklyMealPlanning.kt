package com.lokeshvadlamudi.veggieprep.ai

import com.lokeshvadlamudi.veggieprep.data.IndianIngredientCatalog
import com.lokeshvadlamudi.veggieprep.data.MealIngredient
import com.lokeshvadlamudi.veggieprep.data.MealProposal
import com.lokeshvadlamudi.veggieprep.data.PantryItem
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.temporal.TemporalAdjusters

object WeeklyMealPlanningPolicy {
    const val DEFAULT_MEAL_COUNT = 5

    fun nextWeekStart(today: LocalDate = LocalDate.now()): LocalDate =
        today.with(TemporalAdjusters.nextOrSame(DayOfWeek.MONDAY))

    /** Returns a virtual pantry after reserving ingredients for meals that have not been cooked yet. */
    fun remainingPantry(
        pantry: List<PantryItem>,
        plannedMeals: List<MealProposal>,
    ): List<PantryItem> {
        val reservedByLot = plannedMeals
            .flatMap { it.allocations }
            .groupBy { it.lotId }
            .mapValues { (_, allocations) -> allocations.sumOf { it.quantityMilli } }
        return pantry.mapNotNull { item ->
            val remaining = item.quantityMilli - reservedByLot.getOrDefault(item.id, 0L)
            require(remaining >= 0L) { "A weekly meal tried to reserve more ${item.name} than is available." }
            item.copy(quantityMilli = remaining).takeIf { remaining > 0L }
        }
    }

    fun combinedMissing(meals: List<MealProposal>): List<MealIngredient> = meals
        .flatMap { it.missingIngredients }
        .groupBy { IndianIngredientCatalog.canonicalKey(it.name) to it.unit }
        .map { (_, ingredients) ->
            ingredients.first().copy(quantityMilli = ingredients.sumOf { it.quantityMilli })
        }
        .sortedBy { it.name.lowercase() }
}

package com.lokeshvadlamudi.veggieprep.ai

import com.lokeshvadlamudi.veggieprep.data.MealAllocation
import com.lokeshvadlamudi.veggieprep.data.MealIngredient
import com.lokeshvadlamudi.veggieprep.data.MealProposal
import com.lokeshvadlamudi.veggieprep.data.PantryItem
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class WeeklyMealPlanningPolicyTest {
    @Test fun reservesEachLotAcrossTheWholeWeekWithoutDoubleCounting() {
        val pantry = listOf(pantry(1, "Spinach", 200_000), pantry(2, "Tomatoes", 4_000, "count"))
        val first = meal(
            allocations = listOf(
                MealAllocation(1, "Spinach", "g", 150_000, "2026-08-23", true),
                MealAllocation(2, "Tomatoes", "count", 2_000, "2026-08-25", false),
            ),
        )

        val remaining = WeeklyMealPlanningPolicy.remainingPantry(pantry, listOf(first))

        assertEquals(50_000L, remaining.first { it.id == 1L }.quantityMilli)
        assertEquals(2_000L, remaining.first { it.id == 2L }.quantityMilli)
    }

    @Test fun combinesMissingIngredientsAcrossMeals() {
        val first = meal(missing = listOf(MealIngredient("Tomatoes", "count", 2_000)))
        val second = meal(missing = listOf(MealIngredient("Tomato", "count", 1_000)))

        val combined = WeeklyMealPlanningPolicy.combinedMissing(listOf(first, second))

        assertEquals(1, combined.size)
        assertEquals(3_000L, combined.single().quantityMilli)
        assertTrue(combined.single().name.startsWith("Tomato"))
    }

    private fun pantry(id: Long, name: String, quantity: Long, unit: String = "g") = PantryItem(
        id = id,
        name = name,
        quantityMilli = quantity,
        unit = unit,
        location = "fridge",
        purchasedOn = "2026-08-22",
        expiresOn = "2026-08-25",
    )

    private fun meal(
        allocations: List<MealAllocation> = emptyList(),
        missing: List<MealIngredient> = emptyList(),
    ) = MealProposal(
        title = "Test meal",
        servings = 2,
        timeMinutes = 30,
        steps = listOf("Cook."),
        substitutions = emptyList(),
        safetyNote = "",
        rationale = "",
        ingredients = emptyList(),
        provider = "test",
        allocations = allocations,
        missingIngredients = missing,
    )
}

package com.lokeshvadlamudi.veggieprep.ai

import com.lokeshvadlamudi.veggieprep.data.MealIngredient
import com.lokeshvadlamudi.veggieprep.data.MealProposal
import com.lokeshvadlamudi.veggieprep.data.PantryItem
import java.time.LocalDate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class MealPlanningPolicyTest {
    private val today = LocalDate.parse("2026-08-19")
    private val spinach = pantry(1, "Spinach", 200_000, "g", "2026-08-20")
    private val tomatoes = pantry(2, "Tomatoes", 4_000, "count", "2026-08-22")

    @Test fun requiresEarliestSafeItemAndReconcilesOwnedAndMissingQuantities() {
        val meal = meal(
            MealIngredient("palak", "g", 150_000),
            MealIngredient("Tomato", "count", 6_000),
            MealIngredient("Cooking oil", "ml", 10_000),
        )

        val result = MealPlanningPolicy.reconcile(
            meal = meal,
            pantry = listOf(tomatoes, spinach),
            requiredItem = spinach,
            requestedServings = 2,
            maxMinutes = 30,
            today = today,
        )

        assertEquals(2, result.allocations.size)
        assertEquals(150_000, result.allocations.first { it.lotId == 1L }.quantityMilli)
        assertTrue(result.allocations.first { it.lotId == 1L }.rescued)
        assertEquals(2_000, result.missingIngredients.first { it.name == "Tomato" }.quantityMilli)
        assertEquals(10_000, result.missingIngredients.first { it.name == "Cooking oil" }.quantityMilli)
    }

    @Test fun rejectsSuggestionThatSkipsTheEarliestExpiringItem() {
        assertThrows(IllegalArgumentException::class.java) {
            MealPlanningPolicy.reconcile(
                meal = meal(MealIngredient("Tomatoes", "count", 2_000)),
                pantry = listOf(spinach, tomatoes),
                requiredItem = spinach,
                requestedServings = 2,
                maxMinutes = 30,
                today = today,
            )
        }
    }

    @Test fun excludesExpiredLotsAndConvertsKilogramsToGrams() {
        val expired = pantry(3, "Carrots", 2_000, "count", "2026-08-18")
        val rice = pantry(4, "Rice", 1_000, "kg", "2026-09-01")
        val result = MealPlanningPolicy.reconcile(
            meal = meal(MealIngredient("Rice", "g", 500_000)),
            pantry = listOf(expired, rice),
            requiredItem = rice,
            requestedServings = 2,
            maxMinutes = 30,
            today = today,
        )

        assertEquals(listOf(rice), MealPlanningPolicy.eligiblePantry(listOf(expired, rice), today))
        assertEquals(500, result.allocations.single().quantityMilli)
        assertTrue(result.missingIngredients.isEmpty())
    }

    @Test fun allocatesMatchingLotsInExpiryOrderEvenWhenInputIsUnsorted() {
        val laterSpinach = pantry(5, "Spinach", 200_000, "g", "2026-08-24")
        val result = MealPlanningPolicy.reconcile(
            meal = meal(MealIngredient("palak", "g", 250_000)),
            pantry = listOf(laterSpinach, spinach),
            requiredItem = spinach,
            requestedServings = 2,
            maxMinutes = 30,
            today = today,
        )

        assertEquals(listOf(1L, 5L), result.allocations.map { it.lotId })
        assertEquals(listOf(200_000L, 50_000L), result.allocations.map { it.quantityMilli })
    }

    @Test fun convertsPoundsAndOuncesToGrams() {
        val potatoes = pantry(6, "Potatoes", 5_000, "lb", "2026-08-24")
        val result = MealPlanningPolicy.reconcile(
            meal = meal(MealIngredient("Potatoes", "oz", 16_000)),
            pantry = listOf(potatoes),
            requiredItem = potatoes,
            requestedServings = 2,
            maxMinutes = 30,
            today = today,
        )

        assertEquals(1_000L, result.allocations.single().quantityMilli)
        assertTrue(result.missingIngredients.isEmpty())
    }

    private fun meal(vararg ingredients: MealIngredient) = MealProposal(
        title = "Test meal",
        servings = 2,
        timeMinutes = 20,
        steps = listOf("Cook."),
        substitutions = emptyList(),
        safetyNote = "",
        rationale = "Uses the pantry.",
        ingredients = ingredients.toList(),
        provider = "test",
    )

    private fun pantry(id: Long, name: String, quantity: Long, unit: String, expiry: String) = PantryItem(
        id = id,
        name = name,
        quantityMilli = quantity,
        unit = unit,
        location = "fridge",
        purchasedOn = "2026-08-19",
        expiresOn = expiry,
    )
}

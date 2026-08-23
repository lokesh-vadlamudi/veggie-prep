package com.lokeshvadlamudi.veggieprep.ai

import com.lokeshvadlamudi.veggieprep.data.MealAllocation
import com.lokeshvadlamudi.veggieprep.data.MealIngredient
import com.lokeshvadlamudi.veggieprep.data.MealProposal
import com.lokeshvadlamudi.veggieprep.data.PantryItem
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class WeeklyMealPlanningPolicyTest {
    @Test fun createsBreakfastLunchAndDinnerSlotsForEveryDay() {
        assertEquals(listOf("Breakfast", "Lunch", "Dinner"), WeeklyMealPlanningPolicy.mealSlots(3))
        assertEquals(21, WeeklyMealPlanningPolicy.totalMealCount(7, 3))
        assertEquals(6, WeeklyMealPlanningPolicy.totalMealCount(3, 2))
        assertEquals(listOf("Dinner"), WeeklyMealPlanningPolicy.mealSlots(1))
        assertEquals(
            listOf(
                MealScheduleSlot("2026-08-24", "Lunch"),
                MealScheduleSlot("2026-08-24", "Dinner"),
                MealScheduleSlot("2026-08-25", "Lunch"),
                MealScheduleSlot("2026-08-25", "Dinner"),
            ),
            WeeklyMealPlanningPolicy.scheduleSlots(java.time.LocalDate.parse("2026-08-24"), 2, 2),
        )
    }

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

    @Test fun reconcilesTheWholeScheduleWithoutDoubleUsingPantry() {
        val pantry = listOf(pantry(1, "Spinach", 200_000))
        val meals = listOf(
            meal(ingredients = listOf(MealIngredient("Spinach", "g", 150_000))),
            meal(ingredients = listOf(MealIngredient("Spinach", "g", 100_000))),
        )

        val reconciled = WeeklyMealPlanningPolicy.reconcileSchedule(
            meals = meals,
            pantry = pantry,
            requestedServings = 2,
            maxMinutes = 30,
            today = java.time.LocalDate.parse("2026-08-23"),
        )

        assertEquals(200_000L, reconciled.flatMap { it.allocations }.sumOf { it.quantityMilli })
        assertEquals(50_000L, reconciled.last().missingIngredients.single().quantityMilli)
        assertTrue(reconciled.first().allocations.single().rescued)
    }

    @Test fun pantryOnlyScheduleRejectsCumulativeOveruse() {
        val pantry = listOf(pantry(1, "Spinach", 200_000))
        val meals = listOf(
            meal(ingredients = listOf(MealIngredient("Spinach", "g", 150_000))),
            meal(ingredients = listOf(MealIngredient("Spinach", "g", 100_000))),
        )

        org.junit.Assert.assertThrows(IllegalArgumentException::class.java) {
            WeeklyMealPlanningPolicy.reconcileSchedule(
                meals = meals,
                pantry = pantry,
                requestedServings = 2,
                maxMinutes = 30,
                today = java.time.LocalDate.parse("2026-08-23"),
                pantryOnly = true,
            )
        }
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
        ingredients: List<MealIngredient> = emptyList(),
    ) = MealProposal(
        title = "Test meal",
        servings = 2,
        timeMinutes = 30,
        steps = listOf("Cook."),
        substitutions = emptyList(),
        safetyNote = "",
        rationale = "",
        ingredients = ingredients,
        provider = "test",
        allocations = allocations,
        missingIngredients = missing,
    )
}

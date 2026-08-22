package com.lokeshvadlamudi.veggieprep.data

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class LocalStoreMealFlowInstrumentedTest {
    private val context: Context = ApplicationProvider.getApplicationContext()
    private val databaseName = "veggie_prep_meal_flow_test.db"
    private lateinit var store: LocalStore

    @Before fun setUp() {
        context.deleteDatabase(databaseName)
        store = LocalStore(context, databaseName)
    }

    @After fun tearDown() {
        store.close()
        context.deleteDatabase(databaseName)
    }

    @Test fun cookingDeductsAtomicallyAndShoppingCombinesMissingQuantities() {
        val lotId = store.addLot("Spinach", 200_000, "g", "fridge", "2026-08-19", "2026-08-20")
        store.updateLotExpiry(lotId, "2026-08-21")
        assertEquals("2026-08-21", store.listPantry().single().expiresOn)
        val missingOil = MealIngredient("Cooking oil", "ml", 10_000)
        val mealId = store.saveMeal(
            MealProposal(
                title = "Spinach stir-fry",
                servings = 2,
                timeMinutes = 20,
                steps = listOf("Cook."),
                substitutions = emptyList(),
                safetyNote = "",
                rationale = "Uses spinach first.",
                ingredients = listOf(MealIngredient("Spinach", "g", 150_000), missingOil),
                provider = "test",
                allocations = listOf(MealAllocation(lotId, "Spinach", "g", 150_000, "2026-08-20", true)),
                missingIngredients = listOf(missingOil),
            ),
        )

        store.cookMeal(mealId)

        assertEquals(50_000, store.listPantry().single().quantityMilli)
        assertEquals(MealStatus.COOKED, store.listMeals().single().status)
        store.addShoppingItems(listOf(missingOil))
        store.addShoppingItems(listOf(missingOil))
        val shopping = store.listShopping().single()
        assertEquals(20_000, shopping.quantityMilli)
        store.setShoppingChecked(shopping.id, true)
        assertTrue(store.listShopping().single().checked)
        store.clearCheckedShopping()
        assertTrue(store.listShopping().isEmpty())
    }

    @Test fun storesSnackCategoryAndAllowsExpiryAndIconEdits() {
        val lotId = store.addLot(
            name = "Potato chips",
            quantityMilli = 200_000,
            unit = "g",
            location = "pantry",
            purchasedOn = "2026-08-19",
            expiresOn = "2026-09-01",
            category = "Snacks",
        )

        assertEquals("Snacks", store.listPantry().single().category)
        store.updateLotDetails(lotId, "Popcorn", "2026-09-15", "🍿")
        assertEquals("Popcorn", store.listPantry().single().name)
        assertEquals("2026-09-15", store.listPantry().single().expiresOn)
        assertEquals("🍿", store.listPantry().single().icon)
        store.updateLotDetails(lotId, "Popcorn", "", "")
        assertEquals(null, store.listPantry().single().expiresOn)
        assertEquals(null, store.listPantry().single().icon)
    }

    @Test fun savesAWeeklyPlanAndLinksMealsToTheirDaysAtomically() {
        val planId = store.saveWeeklyPlan(
            WeeklyPlan(
                weekStart = "2026-08-24",
                servings = 2,
                maxMinutes = 45,
                preference = "vegetarian",
                provider = "test",
            ),
            listOf(
                plannedMeal("Monday meal", "2026-08-24"),
                plannedMeal("Tuesday meal", "2026-08-25"),
            ),
        )

        val plan = requireNotNull(store.latestWeeklyPlan())
        val meals = store.listMeals().filter { it.planId == planId }.sortedBy { it.plannedFor }
        assertEquals(planId, plan.id)
        assertEquals(listOf("2026-08-24", "2026-08-25"), meals.map { it.plannedFor })
    }

    @Test fun consumesACombinedDisplayQuantityAcrossMatchingLots() {
        val first = store.addLot("Eggs", 12_000, "count", "fridge", "2026-08-22", "2026-09-19")
        val second = store.addLot("Eggs", 12_000, "count", "fridge", "2026-08-22", "2026-09-19")

        store.changeQuantityAcrossLots(listOf(first, second), 18_000, "CONSUME", "Used from grouped item")

        val remaining = store.listPantry()
        assertEquals(1, remaining.size)
        assertEquals(second, remaining.single().id)
        assertEquals(6_000L, remaining.single().quantityMilli)
    }

    private fun plannedMeal(title: String, day: String) = MealProposal(
        title = title,
        servings = 2,
        timeMinutes = 30,
        steps = listOf("Cook."),
        substitutions = emptyList(),
        safetyNote = "",
        rationale = "",
        ingredients = listOf(MealIngredient("Spinach", "g", 100_000)),
        provider = "test",
        plannedFor = day,
    )
}

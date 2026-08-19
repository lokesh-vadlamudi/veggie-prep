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
}

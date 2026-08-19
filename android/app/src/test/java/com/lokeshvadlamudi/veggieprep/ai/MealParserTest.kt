package com.lokeshvadlamudi.veggieprep.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class MealParserTest {
    @Test fun parsesJsonEvenWhenModelAddsFences() {
        val meal = MealParser.parse(
            """Here you go:
                ```json
                {"title":"Vegetable soup","servings":2,"time_minutes":30,
                 "steps":["Simmer vegetables."],"substitutions":[],"safety_note":"",
                 "rationale":"Uses the spinach first.",
                 "ingredients":[{"name":"Spinach","unit":"g","quantity":"250"}]}
                ```
            """.trimIndent(),
            "test-model",
        )
        assertEquals("Vegetable soup", meal.title)
        assertEquals(250_000L, meal.ingredients.single().quantityMilli)
        assertEquals("test-model", meal.provider)
    }

    @Test fun rejectsUnsupportedUnits() {
        val invalid = """{"title":"Soup","servings":2,"time_minutes":30,
            "steps":["Cook."],"ingredients":[{"name":"Salt","unit":"pinch","quantity":"1"}]}"""
        assertThrows(IllegalArgumentException::class.java) { MealParser.parse(invalid, "test") }
    }
}

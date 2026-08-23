package com.lokeshvadlamudi.veggieprep.ai

import com.lokeshvadlamudi.veggieprep.data.PantryItem
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class WeeklyMealParserTest {
    private val schedule = listOf(
        MealScheduleSlot("2026-08-24", "Breakfast"),
        MealScheduleSlot("2026-08-24", "Lunch"),
    )

    @Test fun parsesAllSlotsAndReturnsThemInScheduleOrder() {
        val raw = """
            {"meals":[
              ${mealJson("2026-08-24", "Lunch", "Mexican", "Bean tacos")},
              ${mealJson("2026-08-24", "Breakfast", "Indian", "Vegetable poha")}
            ]}
        """.trimIndent()

        val meals = WeeklyMealParser.parse(raw, "test", schedule, 3, 45)

        assertEquals(listOf("Breakfast", "Lunch"), meals.map { it.mealType })
        assertEquals(listOf("Vegetable poha", "Bean tacos"), meals.map { it.title })
        assertEquals("Indian cuisine", meals.first().rationale)
        assertTrue(meals.all { it.servings == 3 })
    }

    @Test fun rejectsAnIncompleteOrDuplicateSchedule() {
        val incomplete = """{"meals":[${mealJson("2026-08-24", "Breakfast", "Indian", "Poha")}] }"""
        assertThrows(IllegalArgumentException::class.java) {
            WeeklyMealParser.parse(incomplete, "test", schedule, 3, 45)
        }

        val duplicate = """
            {"meals":[
              ${mealJson("2026-08-24", "Breakfast", "Indian", "Poha")},
              ${mealJson("2026-08-24", "Breakfast", "Italian", "Toast")}
            ]}
        """.trimIndent()
        assertThrows(IllegalArgumentException::class.java) {
            WeeklyMealParser.parse(duplicate, "test", schedule, 3, 45)
        }
    }

    @Test fun weeklyPromptContainsOnlyAllowedPantryFieldsAndAllSlots() {
        val prompt = WeeklyMealPrompt.create(
            pantry = listOf(
                PantryItem(
                    id = 1,
                    name = "Spinach",
                    quantityMilli = 2_000,
                    unit = "count",
                    location = "secret fridge shelf",
                    purchasedOn = "2026-08-22",
                    expiresOn = "2026-08-28",
                    sourceLabel = "private receipt label",
                ),
            ),
            servings = 3,
            maxMinutes = 45,
            preference = "Indian and Mexican",
            schedule = schedule,
        )

        assertTrue(prompt.contains("complete schedule in one response"))
        assertTrue(prompt.contains("2026-08-24"))
        assertTrue(prompt.contains("Breakfast"))
        assertTrue(prompt.contains("Lunch"))
        assertTrue(prompt.contains("Spinach"))
        assertTrue(prompt.contains("Use ONLY ingredients listed in the pantry"))
        assertFalse(prompt.contains("secret fridge shelf"))
        assertFalse(prompt.contains("2026-08-22"))
        assertFalse(prompt.contains("private receipt label"))
    }

    private fun mealJson(date: String, type: String, cuisine: String, title: String): String = """
        {"planned_for":"$date","meal_type":"$type","title":"$title","cuisine":"$cuisine",
         "servings":3,"time_minutes":30,
         "ingredients":[{"name":"Spinach","unit":"count","quantity":"1"}],
         "steps":["Prepare ingredients.","Cook until ready."],"safety_note":""}
    """.trimIndent()
}

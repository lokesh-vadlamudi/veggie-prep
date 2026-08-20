package com.lokeshvadlamudi.veggieprep.ai

import com.lokeshvadlamudi.veggieprep.data.PantryItem
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MealPromptPrivacyTest {
    @Test fun includesNeededMealDataButExcludesStorageAndPurchaseDetails() {
        val prompt = MealPrompt.create(
            pantry = listOf(
                PantryItem(
                    id = 1,
                    name = "Carrots",
                    quantityMilli = 2_000,
                    unit = "count",
                    location = "private-freezer-label",
                    purchasedOn = "2026-08-01",
                    expiresOn = "2026-08-22",
                ),
            ),
            servings = 2,
            maxMinutes = 30,
            preference = "spicy",
        )

        assertTrue(prompt.contains("Carrots"))
        assertTrue(prompt.contains("2026-08-22"))
        assertTrue(prompt.contains("spicy"))
        assertFalse(prompt.contains("location"))
        assertFalse(prompt.contains("private-freezer-label"))
        assertFalse(prompt.contains("purchased_on"))
        assertFalse(prompt.contains("2026-08-01"))
    }
}

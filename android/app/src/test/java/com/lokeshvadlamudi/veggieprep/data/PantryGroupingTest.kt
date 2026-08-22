package com.lokeshvadlamudi.veggieprep.data

import org.junit.Assert.assertEquals
import org.junit.Test

class PantryGroupingTest {
    @Test fun combinesMatchingLotsForDisplay() {
        val groups = groupMatchingPantryItems(
            listOf(
                pantry(1, "Egg", "2026-09-19", 12_000),
                pantry(2, "Eggs", "2026-09-19", 12_000),
            ),
        )

        assertEquals(1, groups.size)
        assertEquals(24_000L, groups.single().summary.quantityMilli)
        assertEquals(listOf(1L, 2L), groups.single().lots.map(PantryItem::id))
    }

    @Test fun keepsDifferentExpiryDatesAndIconsSeparate() {
        val groups = groupMatchingPantryItems(
            listOf(
                pantry(1, "Eggs", "2026-09-19", 12_000),
                pantry(2, "Eggs", "2026-09-26", 12_000),
                pantry(3, "Eggs", "2026-09-19", 12_000).copy(icon = "🍳"),
            ),
        )

        assertEquals(3, groups.size)
    }

    @Test fun keepsDifferentReceiptVariantsSeparateEvenWhenTheirStoredNamesMatch() {
        val groups = groupMatchingPantryItems(
            listOf(
                pantry(1, "Hummus", "2026-09-01", 300_000).copy(sourceLabel = "HUMMUS MEDITERRANEAN"),
                pantry(2, "Hummus", "2026-09-01", 300_000).copy(sourceLabel = "HUMMUS ROASTED RED PEPPE"),
            ),
        )

        assertEquals(2, groups.size)
    }

    private fun pantry(id: Long, name: String, expiry: String, quantity: Long) = PantryItem(
        id = id,
        name = name,
        quantityMilli = quantity,
        unit = "count",
        location = "fridge",
        purchasedOn = "2026-08-22",
        expiresOn = expiry,
    )
}

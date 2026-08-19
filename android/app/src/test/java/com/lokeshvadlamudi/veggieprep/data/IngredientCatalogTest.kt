package com.lokeshvadlamudi.veggieprep.data

import java.time.LocalDate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class IngredientCatalogTest {
    @Test fun findsRegionalAliasesAndPluralVariants() {
        assertEquals("spinach", IndianIngredientCatalog.search("palak").first().id)
        assertEquals("spinach", IndianIngredientCatalog.search("palakura").first().id)
        assertEquals("tomato", IndianIngredientCatalog.canonicalKey("Tomato"))
        assertEquals("tomato", IndianIngredientCatalog.canonicalKey("Tomatoes"))
        assertTrue(IndianIngredientCatalog.items.size >= 100)
    }

    @Test fun providesEditableDefaultQuantityStorageAndExpiry() {
        val spinach = requireNotNull(IndianIngredientCatalog.find("keerai"))

        assertEquals("200", spinach.defaultQuantity)
        assertEquals("g", spinach.defaultUnit)
        assertEquals("fridge", spinach.defaultStorage)
        assertEquals("2026-08-23", spinach.suggestedExpiry(LocalDate.parse("2026-08-19")))
    }
}

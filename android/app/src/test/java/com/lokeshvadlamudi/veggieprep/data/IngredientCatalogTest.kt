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
        assertTrue(IndianIngredientCatalog.items.size >= 450)
    }

    @Test fun coversBreadsEggsProteinsPreparedFoodsAndGlobalPantryItems() {
        assertEquals("eggs", IndianIngredientCatalog.search("egg").first().id)
        assertEquals("sourdough-bread", IndianIngredientCatalog.search("sourdough").first().id)
        assertEquals("roti", IndianIngredientCatalog.search("roti").first().id)
        assertEquals("cottage-cheese", IndianIngredientCatalog.canonicalKey("cottage cheese"))
        assertEquals("paneer", IndianIngredientCatalog.canonicalKey("paneer"))
        assertEquals("idli-batter", IndianIngredientCatalog.search("idly batter").first().id)
        assertEquals("leftovers", IndianIngredientCatalog.search("leftover meal").first().id)
        assertTrue(IndianIngredientCatalog.items.count { it.category == "Breads & flatbreads" } >= 40)
        assertEquals(IndianIngredientCatalog.items.size, IndianIngredientCatalog.items.map { it.id }.distinct().size)
        assertTrue(IndianIngredientCatalog.isSnack("Potato chips"))
        assertTrue(IndianIngredientCatalog.isSnack("Family recipe crunch", "Snacks"))
    }

    @Test fun providesEditableDefaultQuantityStorageAndExpiry() {
        val spinach = requireNotNull(IndianIngredientCatalog.find("keerai"))

        assertEquals("200", spinach.defaultQuantity)
        assertEquals("g", spinach.defaultUnit)
        assertEquals("fridge", spinach.defaultStorage)
        assertEquals("2026-08-23", spinach.suggestedExpiry(LocalDate.parse("2026-08-19")))
    }
}

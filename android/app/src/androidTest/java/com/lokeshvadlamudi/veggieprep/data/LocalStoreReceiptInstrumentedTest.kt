package com.lokeshvadlamudi.veggieprep.data

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.lokeshvadlamudi.veggieprep.receipt.ReceiptCandidate
import com.lokeshvadlamudi.veggieprep.receipt.ReceiptConfidence
import com.lokeshvadlamudi.veggieprep.receipt.ReceiptDraft
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class LocalStoreReceiptInstrumentedTest {
    private val context: Context = ApplicationProvider.getApplicationContext()
    private val databaseName = "veggie_prep_receipt_test.db"
    private lateinit var store: LocalStore

    @Before fun setUp() {
        context.deleteDatabase(databaseName)
        store = LocalStore(context, databaseName)
    }

    @After fun tearDown() {
        store.close()
        context.deleteDatabase(databaseName)
    }

    @Test fun importIsAtomicRejectsDuplicatesAndCanBeUndone() {
        val result = store.importReceipt(draft())
        val item = store.listPantry().single()

        assertEquals("Potatoes", item.name)
        assertEquals(5_000L, item.quantityMilli)
        assertEquals("lb", item.unit)
        assertEquals("receipt", item.source)
        assertEquals(result.importId, item.sourceRef)
        assertEquals(true, item.expiryEstimated)
        assertThrows(IllegalArgumentException::class.java) { store.importReceipt(draft()) }

        store.undoReceiptImport(result.importId)

        assertFalse(store.listPantry().isNotEmpty())
    }

    @Test fun undoStopsAfterAnImportedItemHasBeenUsed() {
        val result = store.importReceipt(draft())
        val item = store.listPantry().single()
        store.changeQuantity(item.id, 1_000, "CONSUME", "Used in test")

        assertThrows(IllegalArgumentException::class.java) { store.undoReceiptImport(result.importId) }
        assertEquals(4_000L, store.listPantry().single().quantityMilli)
    }

    private fun draft() = ReceiptDraft(
        fingerprint = "sanitized-receipt-fingerprint",
        merchant = "Grocery store",
        purchasedOn = "2026-08-22",
        candidates = listOf(
            ReceiptCandidate(
                id = "potatoes",
                rawLabel = "POTATO BAG GOLD 5 LB",
                name = "Potatoes",
                quantityMilli = 5_000,
                unit = "lb",
                location = "pantry",
                category = "Vegetables",
                expiresOn = "2026-09-12",
                expiryEstimated = true,
                quantityEstimated = false,
                confidence = ReceiptConfidence.HIGH,
                included = true,
                matchReason = "Matched",
            ),
            ReceiptCandidate(
                id = "unknown",
                rawLabel = "UNNAMED GROCERY",
                name = "Unnamed grocery",
                quantityMilli = 1_000,
                unit = "count",
                location = "pantry",
                category = "Other",
                expiresOn = "",
                expiryEstimated = false,
                quantityEstimated = true,
                confidence = ReceiptConfidence.LOW,
                included = false,
                matchReason = "Needs review",
            ),
        ),
        skippedLineCount = 0,
    )
}

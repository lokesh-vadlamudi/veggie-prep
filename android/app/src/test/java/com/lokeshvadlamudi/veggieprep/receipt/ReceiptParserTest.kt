package com.lokeshvadlamudi.veggieprep.receipt

import java.time.LocalDate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ReceiptParserTest {
    @Test fun parsesSanitizedTraderJoesReceiptAndFlagsUnnamedLine() {
        val draft = ReceiptParser.parse(
            listOf(
                "TRADER JOE'S",
                "SALE TRANSACTION",
                "A-POTATO BAG GOLD 5 LB $4.99",
                "SAUCE CHIMICHURRI $7.98",
                "2 @ $3.99",
                "HUMMUS MEDITERRANEAN $4.29",
                "COTTAGE CHEESE PINT WHOL $2.99",
                "A-AVOCADO BAG HASS MEDIU $4.49",
                "HUMMUS ROASTED RED PEPPE $3.49",
                "PEPPER MINI SWEET ORG 1L $3.99",
                "POTATO SWEET EACH $2.97",
                "3 @ $0.99",
                "Grocery non-taxable $1.16",
                "4 @ $0.29",
                "Items in Transaction:15",
                "PAYMENT MILK REWARD $9.99",
                "Balance to pay $36.35",
                "VISA $36.35",
            ).map(::ReceiptTextRow),
            today = LocalDate.parse("2026-08-22"),
        )

        assertEquals("Trader Joe's", draft.merchant)
        assertEquals("2026-08-22", draft.purchasedOn)
        assertEquals(9, draft.candidates.size)
        assertEquals(8, draft.includedCount)

        val potatoes = draft.candidates.first { it.name == "Potatoes" }
        assertEquals("lb", potatoes.unit)
        assertEquals(5_000L, potatoes.quantityMilli)
        assertFalse(potatoes.quantityEstimated)

        val chimichurri = draft.candidates.first { it.name == "Chimichurri sauce" }
        assertEquals("ml", chimichurri.unit)
        assertEquals(500_000L, chimichurri.quantityMilli)
        assertTrue(chimichurri.quantityEstimated)

        val peppers = draft.candidates.first { it.name == "Mini sweet peppers" }
        assertEquals("lb", peppers.unit)
        assertEquals(1_000L, peppers.quantityMilli)

        val sweetPotatoes = draft.candidates.first { it.name == "Sweet potato" }
        assertEquals("count", sweetPotatoes.unit)
        assertEquals(3_000L, sweetPotatoes.quantityMilli)

        val ambiguous = draft.candidates.first { it.rawLabel.contains("Grocery", ignoreCase = true) }
        assertEquals(ReceiptConfidence.LOW, ambiguous.confidence)
        assertFalse(ambiguous.included)
        assertEquals(4_000L, ambiguous.quantityMilli)
    }

    @Test fun fingerprintIsStableForTheSameSanitizedRows() {
        val rows = listOf("SALE TRANSACTION", "HUMMUS $4.29", "Balance to pay $4.29").map(::ReceiptTextRow)
        val first = ReceiptParser.parse(rows, LocalDate.parse("2026-08-22"))
        val second = ReceiptParser.parse(rows, LocalDate.parse("2026-08-22"))
        assertEquals(first.fingerprint, second.fingerprint)
    }

    @Test fun acceptsCommonOcrSpacingInsidePrices() {
        val draft = ReceiptParser.parse(
            listOf(
                "SALE TRANSACTION",
                "POTATO BAG GOLD 5 LB $ 4 . 99",
                "SAUCE CHIMICHURRI S 7. 98",
                "2 @ $ 3 . 99",
                "Items in Transaction: 3",
            ).map(::ReceiptTextRow),
            today = LocalDate.parse("2026-08-22"),
        )

        assertEquals(2, draft.candidates.size)
        assertEquals(500_000L, draft.candidates.first { it.name == "Chimichurri sauce" }.quantityMilli)
    }
}

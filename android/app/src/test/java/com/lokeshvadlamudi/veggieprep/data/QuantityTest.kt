package com.lokeshvadlamudi.veggieprep.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class QuantityTest {
    @Test fun parsesUpToThreeDecimalPlacesExactly() {
        assertEquals(1_000L, parseMilli("1"))
        assertEquals(1_250L, parseMilli("1.25"))
        assertEquals(1L, parseMilli("0.001"))
        assertNull(parseMilli("1.0001"))
        assertNull(parseMilli("-1"))
        assertNull(parseMilli("NaN"))
    }

    @Test fun formatsWithoutFloatingPointRounding() {
        assertEquals("2", formatMilli(2_000))
        assertEquals("2.5", formatMilli(2_500))
        assertEquals("0.001", formatMilli(1))
    }
}

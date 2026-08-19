package com.lokeshvadlamudi.veggieprep.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class EndpointValidationTest {
    @Test fun permitsPrivateLanAndTailscaleHttp() {
        assertEquals("http://192.168.1.20:8000/v1", validateAndNormalizeEndpoint("http://192.168.1.20:8000/v1/"))
        assertEquals("http://100.100.1.2:8000/v1", validateAndNormalizeEndpoint("http://100.100.1.2:8000/v1"))
        assertEquals("http://dgx.local:8000/v1", validateAndNormalizeEndpoint("http://dgx.local:8000/v1"))
    }

    @Test fun requiresHttpsForPublicHosts() {
        assertEquals("https://api.openai.com/v1", validateAndNormalizeEndpoint("https://api.openai.com/v1"))
        assertThrows(IllegalArgumentException::class.java) {
            validateAndNormalizeEndpoint("http://api.example.com/v1")
        }
    }

    @Test fun rejectsEmbeddedCredentials() {
        assertThrows(IllegalArgumentException::class.java) {
            validateAndNormalizeEndpoint("https://secret@example.com/v1")
        }
    }
}

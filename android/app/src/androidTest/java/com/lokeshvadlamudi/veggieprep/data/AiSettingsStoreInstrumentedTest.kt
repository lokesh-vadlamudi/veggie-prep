package com.lokeshvadlamudi.veggieprep.data

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AiSettingsStoreInstrumentedTest {
    private val context: Context = ApplicationProvider.getApplicationContext()
    private lateinit var store: AiSettingsStore

    @Before
    fun resetPreferences() {
        context.getSharedPreferences("ai_settings", Context.MODE_PRIVATE).edit().clear().commit()
        store = AiSettingsStore(context)
    }

    @Test
    fun remembersOnlyTheConfirmedEndpointAndCanRevokeIt() {
        val confirmed = "http://10.0.2.2:8765/v1"

        store.rememberNetworkDisclosure("  $confirmed/  ")

        assertTrue(store.isNetworkDisclosureRemembered(confirmed))
        assertTrue(store.isNetworkDisclosureRemembered("$confirmed/"))
        assertFalse(store.isNetworkDisclosureRemembered("http://10.0.2.2:9000/v1"))

        store.forgetNetworkDisclosure("http://10.0.2.2:9000/v1")
        assertTrue(store.isNetworkDisclosureRemembered(confirmed))

        store.forgetNetworkDisclosure(confirmed)
        assertFalse(store.isNetworkDisclosureRemembered(confirmed))
    }
}

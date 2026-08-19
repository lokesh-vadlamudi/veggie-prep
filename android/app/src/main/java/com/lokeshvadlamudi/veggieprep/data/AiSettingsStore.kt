package com.lokeshvadlamudi.veggieprep.data

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class AiSettingsStore(private val context: Context) {
    private val preferences = context.getSharedPreferences("ai_settings", Context.MODE_PRIVATE)
    private val secrets = context.getSharedPreferences("ai_secrets", Context.MODE_PRIVATE)

    fun load(): AiSettings {
        val provider = runCatching {
            AiProviderType.valueOf(preferences.getString("provider", null).orEmpty())
        }.getOrDefault(AiProviderType.GEMINI_NANO)
        return AiSettings(
            provider = provider,
            baseUrl = preferences.getString("base_url", "").orEmpty(),
            model = preferences.getString("model", "").orEmpty(),
            modelPath = preferences.getString("model_path", "").orEmpty(),
            modelDisplayName = preferences.getString("model_name", "").orEmpty(),
        )
    }

    fun save(settings: AiSettings, apiKey: String?) {
        preferences.edit()
            .putString("provider", settings.provider.name)
            .putString("base_url", settings.baseUrl.trim().trimEnd('/'))
            .putString("model", settings.model.trim())
            .putString("model_path", settings.modelPath)
            .putString("model_name", settings.modelDisplayName)
            .apply()
        if (apiKey != null) {
            if (apiKey.isBlank()) secrets.edit().remove("api_key").apply()
            else secrets.edit().putString("api_key", encrypt(apiKey.trim())).apply()
        }
    }

    fun apiKey(): String = secrets.getString("api_key", null)?.let(::decrypt).orEmpty()

    private fun key(): SecretKey {
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (keyStore.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").run {
            init(
                KeyGenParameterSpec.Builder(
                    KEY_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                )
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setRandomizedEncryptionRequired(true)
                    .build(),
            )
            generateKey()
        }
    }

    private fun encrypt(plainText: String): String {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val combined = cipher.iv + cipher.doFinal(plainText.toByteArray(Charsets.UTF_8))
        return Base64.encodeToString(combined, Base64.NO_WRAP)
    }

    private fun decrypt(encoded: String): String = runCatching {
        val combined = Base64.decode(encoded, Base64.NO_WRAP)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, combined.copyOfRange(0, 12)))
        String(cipher.doFinal(combined.copyOfRange(12, combined.size)), Charsets.UTF_8)
    }.getOrDefault("")

    companion object {
        private const val KEY_ALIAS = "veggie_prep_ai_key"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
    }
}

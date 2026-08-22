package com.lokeshvadlamudi.veggieprep.ai

import com.google.gson.JsonArray
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.io.IOException
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.URI
import java.net.URL
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class RemoteOpenAiMealAi(
    baseUrl: String,
    private val model: String,
    private val apiKey: String,
) : MealAi {
    private val baseUrl = validateAndNormalizeEndpoint(baseUrl)

    init {
        require(model.isNotBlank()) { "Enter the model name used by your API." }
    }

    override val label: String = model

    override suspend fun generate(prompt: String): String = withContext(Dispatchers.IO) {
        val body = createRemoteRequestBody(model, prompt).toString()

        val connection = (URL("$baseUrl/chat/completions").openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 15_000
            readTimeout = 120_000
            doOutput = true
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("Accept", "application/json")
            if (apiKey.isNotBlank()) setRequestProperty("Authorization", "Bearer $apiKey")
        }
        try {
            connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val response = stream?.bufferedReader()?.use { reader -> reader.readTextLimited(512 * 1024) }.orEmpty()
            if (code !in 200..299) throw IOException("AI service returned HTTP $code.")
            val root = JsonParser.parseString(response).asJsonObject
            root.getAsJsonArray("choices")
                ?.getOrNull(0)
                ?.asJsonObject
                ?.getAsJsonObject("message")
                ?.get("content")
                ?.asString
                ?: throw IOException("AI service returned an unexpected response.")
        } finally {
            connection.disconnect()
        }
    }
}

internal fun createRemoteRequestBody(model: String, prompt: String): JsonObject = JsonObject().apply {
    val supportsStructuredMealOutput = model.contains("qwen", ignoreCase = true) ||
        model.contains("deepseek", ignoreCase = true)
    addProperty("model", model)
    addProperty("temperature", 0.25)
    addProperty("max_tokens", 3000)
    add("messages", JsonArray().apply {
        add(JsonObject().apply {
            addProperty("role", "user")
            addProperty("content", prompt)
        })
    })
    if (supportsStructuredMealOutput) {
        add("chat_template_kwargs", JsonObject().apply {
            addProperty("enable_thinking", false)
        })
        add("response_format", JsonParser.parseString(STRUCTURED_MEAL_RESPONSE_FORMAT).asJsonObject)
    }
}

private val STRUCTURED_MEAL_RESPONSE_FORMAT = """
    {
      "type": "json_schema",
      "json_schema": {
        "name": "meal_proposal",
        "strict": true,
        "schema": {
          "type": "object",
          "additionalProperties": false,
          "required": ["title", "servings", "time_minutes", "steps", "substitutions", "safety_note", "rationale", "ingredients"],
          "properties": {
            "title": {"type": "string", "maxLength": 160},
            "servings": {"type": "integer", "minimum": 1, "maximum": 20},
            "time_minutes": {"type": "integer", "minimum": 1, "maximum": 360},
            "steps": {
              "type": "array",
              "minItems": 1,
              "maxItems": 15,
              "items": {"type": "string", "maxLength": 500}
            },
            "substitutions": {
              "type": "array",
              "maxItems": 8,
              "items": {"type": "string", "maxLength": 300}
            },
            "safety_note": {"type": "string", "maxLength": 500},
            "rationale": {"type": "string", "maxLength": 600},
            "ingredients": {
              "type": "array",
              "minItems": 1,
              "maxItems": 40,
              "items": {
                "type": "object",
                "additionalProperties": false,
                "required": ["name", "unit", "quantity"],
                "properties": {
                  "name": {"type": "string", "maxLength": 200},
                  "unit": {"type": "string", "enum": ["count", "each", "oz", "lb", "g", "kg", "ml", "l"]},
                  "quantity": {"type": "string", "pattern": "^[0-9]+([.][0-9]{1,3})?$"}
                }
              }
            }
          }
        }
      }
    }
""".trimIndent()

fun validateAndNormalizeEndpoint(value: String): String {
    val trimmed = value.trim().trimEnd('/')
    require(trimmed.isNotEmpty()) { "Enter an API address." }
    val uri = runCatching { URI(trimmed) }.getOrElse { throw IllegalArgumentException("Enter a valid API address.") }
    require(uri.rawUserInfo == null && uri.rawQuery == null && uri.rawFragment == null) {
        "The API address cannot contain credentials, a query, or a fragment."
    }
    val scheme = uri.scheme?.lowercase()
    val host = uri.host?.lowercase() ?: throw IllegalArgumentException("Enter a valid API host.")
    require(scheme == "https" || (scheme == "http" && isPrivateHost(host))) {
        "Public API addresses must use HTTPS. HTTP is allowed only for local LAN or Tailscale addresses."
    }
    return trimmed
}

internal fun isPrivateHost(host: String): Boolean {
    val normalizedHost = host.removePrefix("[").removeSuffix("]")
    if (normalizedHost == "localhost" || normalizedHost.endsWith(".local") || normalizedHost == "::1") return true
    val parts = normalizedHost.split('.').mapNotNull { it.toIntOrNull() }
    if (parts.size != 4 || parts.any { it !in 0..255 }) {
        return normalizedHost.startsWith("fc") || normalizedHost.startsWith("fd")
    }
    val first = parts[0]
    val second = parts[1]
    return first == 10 ||
        first == 127 ||
        (first == 172 && second in 16..31) ||
        (first == 192 && second == 168) ||
        (first == 169 && second == 254) ||
        (first == 100 && second in 64..127)
}

private fun java.io.BufferedReader.readTextLimited(maxChars: Int): String {
    val output = StringBuilder()
    val buffer = CharArray(8192)
    while (true) {
        val count = read(buffer)
        if (count < 0) break
        if (output.length + count > maxChars) throw IOException("AI response was too large.")
        output.append(buffer, 0, count)
    }
    return output.toString()
}

private fun JsonArray.getOrNull(index: Int) = if (index in 0 until size()) get(index) else null

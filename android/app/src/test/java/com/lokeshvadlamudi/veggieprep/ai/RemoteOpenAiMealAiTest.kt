package com.lokeshvadlamudi.veggieprep.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RemoteOpenAiMealAiTest {
    @Test
    fun qwenRequestsDisableThinkingAndRequireMealSchema() {
        val body = createRemoteRequestBody("qwen3.6:35b", "plan a meal")

        assertFalse(
            body.getAsJsonObject("chat_template_kwargs")
                .get("enable_thinking")
                .asBoolean,
        )
        assertEquals(3000, body.get("max_tokens").asInt)
        val responseFormat = body.getAsJsonObject("response_format")
        assertEquals("json_schema", responseFormat.get("type").asString)
        val jsonSchema = responseFormat.getAsJsonObject("json_schema")
        assertTrue(jsonSchema.get("strict").asBoolean)
        val properties = jsonSchema.getAsJsonObject("schema").getAsJsonObject("properties")
        assertTrue(properties.has("ingredients"))
        assertTrue(properties.has("steps"))
    }

    @Test
    fun deepSeekRequestsDisableThinkingAndRequireMealSchema() {
        val body = createRemoteRequestBody("deepseek-v4-flash-0731", "plan a meal")

        assertFalse(
            body.getAsJsonObject("chat_template_kwargs")
                .get("enable_thinking")
                .asBoolean,
        )
        assertEquals(3000, body.get("max_tokens").asInt)
        assertEquals("json_schema", body.getAsJsonObject("response_format").get("type").asString)
    }

    @Test
    fun otherProvidersReceiveThePortableOpenAiRequest() {
        val body = createRemoteRequestBody("gpt-compatible-model", "plan a meal")

        assertFalse(body.has("chat_template_kwargs"))
        assertFalse(body.has("response_format"))
        assertEquals(3000, body.get("max_tokens").asInt)
        assertEquals("plan a meal", body.getAsJsonArray("messages")[0].asJsonObject.get("content").asString)
    }
}

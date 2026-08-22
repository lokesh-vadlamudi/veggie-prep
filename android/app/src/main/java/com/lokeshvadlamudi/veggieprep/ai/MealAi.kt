package com.lokeshvadlamudi.veggieprep.ai

import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.lokeshvadlamudi.veggieprep.data.MealIngredient
import com.lokeshvadlamudi.veggieprep.data.MealProposal
import com.lokeshvadlamudi.veggieprep.data.PantryItem
import com.lokeshvadlamudi.veggieprep.data.parseMilli

interface MealAi {
    val label: String
    suspend fun generate(prompt: String): String
    suspend fun generateSchedule(prompt: String, mealCount: Int): String = generate(prompt)
}

object MealPrompt {
    private val gson = Gson()

    fun create(
        pantry: List<PantryItem>,
        servings: Int,
        maxMinutes: Int,
        preference: String,
        requiredItem: PantryItem? = MealPlanningPolicy.requiredExpiryItem(pantry),
    ): String {
        val inventory = MealPlanningPolicy.eligiblePantry(pantry).map {
            mapOf(
                "name" to it.name,
                "quantity" to it.quantityText,
                "unit" to it.unit,
                "expires_on" to it.expiresOn,
            )
        }
        return """
            You are a practical meal planner. Plan one meal using this pantry.
            ${requiredItem?.let { "You MUST use ${it.name}, the earliest-expiring safe item." } ?: "Prefer dated ingredients before undated ingredients."}
            Never claim an ingredient is present unless it is listed. You may include missing staples, but they must appear in ingredients.
            Do not exceed the listed pantry quantities. Expired items have already been excluded.
            Return exactly one JSON object, without Markdown or commentary, using this schema:
            {
              "title": "short dish name",
              "servings": $servings,
              "time_minutes": integer not greater than $maxMinutes,
              "steps": ["1 to 12 short cooking steps"],
              "substitutions": ["optional swaps"],
              "safety_note": "short safety note or empty string",
              "rationale": "why this meal fits",
              "ingredients": [{"name":"ingredient", "unit":"count|each|oz|lb|g|kg|ml|l", "quantity":"number with at most 3 decimals"}]
            }

            Preference: ${preference.ifBlank { "No special preference" }}
            Pantry: ${gson.toJson(inventory)}
        """.trimIndent()
    }
}

object MealParser {
    fun parse(raw: String, provider: String): MealProposal {
        val objectText = extractJsonObject(raw)
        val root = JsonParser.parseString(objectText).asJsonObject
        val title = root.requiredString("title", 160)
        val servings = root.requiredInt("servings", 1, 20)
        val time = root.requiredInt("time_minutes", 1, 360)
        val steps = root.requiredStrings("steps", 1, 15, 500)
        val substitutions = root.optionalStrings("substitutions", 8, 300)
        val safety = root.optionalString("safety_note", 500)
        val rationale = root.optionalString("rationale", 600)
        val ingredientsJson = root.getAsJsonArray("ingredients")
            ?: throw IllegalArgumentException("The model did not return ingredients.")
        require(ingredientsJson.size() in 1..40) { "The model returned an invalid ingredient list." }
        val allowedUnits = setOf("count", "each", "oz", "lb", "g", "kg", "ml", "l")
        val ingredients = ingredientsJson.map { element ->
            val item = element.asJsonObject
            val name = item.requiredString("name", 200)
            val unit = item.requiredString("unit", 10)
            require(unit in allowedUnits) { "The model returned an unsupported unit: $unit" }
            val quantityText = item.get("quantity")?.asString.orEmpty()
            val quantity = parseMilli(quantityText)
                ?: throw IllegalArgumentException("The model returned an invalid ingredient quantity.")
            require(quantity > 0) { "Ingredient quantities must be positive." }
            MealIngredient(name, unit, quantity)
        }
        return MealProposal(
            title = title,
            servings = servings,
            timeMinutes = time,
            steps = steps,
            substitutions = substitutions,
            safetyNote = safety,
            rationale = rationale,
            ingredients = ingredients,
            provider = provider,
        )
    }

    internal fun extractJsonObject(text: String): String {
        val start = text.indexOf('{')
        require(start >= 0) { "The model did not return JSON." }
        var depth = 0
        var inString = false
        var escaped = false
        for (index in start until text.length) {
            val char = text[index]
            if (inString) {
                if (escaped) escaped = false
                else if (char == '\\') escaped = true
                else if (char == '"') inString = false
            } else {
                when (char) {
                    '"' -> inString = true
                    '{' -> depth++
                    '}' -> {
                        depth--
                        if (depth == 0) return text.substring(start, index + 1)
                    }
                }
            }
        }
        throw IllegalArgumentException("The model returned incomplete JSON.")
    }
}

private fun JsonObject.requiredString(name: String, max: Int): String {
    val value = get(name)?.takeUnless { it.isJsonNull }?.asString?.trim().orEmpty()
    require(value.isNotEmpty() && value.length <= max) { "Invalid $name in model response." }
    return value
}

private fun JsonObject.optionalString(name: String, max: Int): String {
    val value = get(name)?.takeUnless { it.isJsonNull }?.asString?.trim().orEmpty()
    require(value.length <= max) { "Invalid $name in model response." }
    return value
}

private fun JsonObject.requiredInt(name: String, minimum: Int, maximum: Int): Int {
    val value = get(name)?.asInt ?: throw IllegalArgumentException("Missing $name in model response.")
    require(value in minimum..maximum) { "Invalid $name in model response." }
    return value
}

private fun JsonObject.requiredStrings(name: String, minimum: Int, maximum: Int, maxLength: Int): List<String> {
    val array = getAsJsonArray(name) ?: throw IllegalArgumentException("Missing $name in model response.")
    require(array.size() in minimum..maximum) { "Invalid $name in model response." }
    return array.map { it.asString.trim() }.also { values ->
        require(values.all { it.isNotEmpty() && it.length <= maxLength }) { "Invalid $name in model response." }
    }
}

private fun JsonObject.optionalStrings(name: String, maximum: Int, maxLength: Int): List<String> {
    if (!has(name) || get(name).isJsonNull) return emptyList()
    val array = getAsJsonArray(name) ?: throw IllegalArgumentException("Invalid $name in model response.")
    require(array.size() <= maximum) { "Invalid $name in model response." }
    return array.map { it.asString.trim() }.also { values ->
        require(values.all { it.isNotEmpty() && it.length <= maxLength }) { "Invalid $name in model response." }
    }
}

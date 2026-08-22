package com.lokeshvadlamudi.veggieprep.data

data class PantryItem(
    val id: Long,
    val name: String,
    val quantityMilli: Long,
    val unit: String,
    val location: String,
    val purchasedOn: String?,
    val expiresOn: String?,
    val category: String = "Other",
    val expiryEstimated: Boolean = false,
    val quantityEstimated: Boolean = false,
    val source: String = "manual",
    val sourceRef: Long? = null,
    val icon: String? = null,
    val sourceLabel: String? = null,
) {
    val quantityText: String
        get() = formatMilli(quantityMilli)
}

data class MealIngredient(
    val name: String,
    val unit: String,
    val quantityMilli: Long,
)

data class MealAllocation(
    val lotId: Long,
    val name: String,
    val unit: String,
    val quantityMilli: Long,
    val expiresOn: String?,
    val rescued: Boolean,
)

enum class MealStatus {
    SUGGESTED,
    COOKED,
}

data class MealProposal(
    val id: Long = 0,
    val title: String,
    val servings: Int,
    val timeMinutes: Int,
    val steps: List<String>,
    val substitutions: List<String>,
    val safetyNote: String,
    val rationale: String,
    val ingredients: List<MealIngredient>,
    val provider: String,
    val allocations: List<MealAllocation> = emptyList(),
    val missingIngredients: List<MealIngredient> = emptyList(),
    val status: MealStatus = MealStatus.SUGGESTED,
    val cookedAt: Long? = null,
    val createdAt: Long = System.currentTimeMillis(),
    val planId: Long? = null,
    val plannedFor: String? = null,
    val mealType: String? = null,
)

data class WeeklyPlan(
    val id: Long = 0,
    val weekStart: String,
    val servings: Int,
    val maxMinutes: Int,
    val mealsPerDay: Int = 1,
    val daysCount: Int = 7,
    val preference: String,
    val provider: String,
    val createdAt: Long = System.currentTimeMillis(),
)

data class ShoppingItem(
    val id: Long,
    val name: String,
    val quantityMilli: Long,
    val unit: String,
    val checked: Boolean,
) {
    val quantityText: String
        get() = formatMilli(quantityMilli)
}

enum class AiProviderType {
    REMOTE_OPENAI,
    GEMINI_NANO,
    ON_DEVICE_MODEL,
}

data class AiSettings(
    val provider: AiProviderType = AiProviderType.GEMINI_NANO,
    val baseUrl: String = "",
    val model: String = "",
    val modelPath: String = "",
    val modelDisplayName: String = "",
)

fun formatMilli(value: Long): String {
    val whole = value / 1000
    val fraction = kotlin.math.abs(value % 1000)
    return if (fraction == 0L) whole.toString() else "$whole.${fraction.toString().padStart(3, '0').trimEnd('0')}"
}

fun parseMilli(text: String): Long? {
    val normalized = text.trim()
    if (!Regex("^[0-9]+(?:\\.[0-9]{1,3})?$").matches(normalized)) return null
    val parts = normalized.split('.', limit = 2)
    val whole = parts[0].toLongOrNull() ?: return null
    val fraction = parts.getOrNull(1)?.padEnd(3, '0')?.toLongOrNull() ?: 0L
    return try {
        Math.addExact(Math.multiplyExact(whole, 1000L), fraction)
    } catch (_: ArithmeticException) {
        null
    }
}

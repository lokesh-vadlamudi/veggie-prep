package com.lokeshvadlamudi.veggieprep.ai

import com.google.gson.Gson
import com.google.gson.JsonParser
import com.lokeshvadlamudi.veggieprep.data.IndianIngredientCatalog
import com.lokeshvadlamudi.veggieprep.data.MealIngredient
import com.lokeshvadlamudi.veggieprep.data.MealProposal
import com.lokeshvadlamudi.veggieprep.data.PantryItem
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.temporal.TemporalAdjusters

data class MealScheduleSlot(
    val plannedFor: String,
    val mealType: String,
)

object WeeklyMealPlanningPolicy {
    const val DEFAULT_DAYS = 7

    fun mealSlots(mealsPerDay: Int): List<String> = when (mealsPerDay.coerceIn(1, 3)) {
        1 -> listOf("Dinner")
        2 -> listOf("Lunch", "Dinner")
        else -> listOf("Breakfast", "Lunch", "Dinner")
    }

    fun totalMealCount(days: Int, mealsPerDay: Int): Int =
        days.coerceIn(1, 14) * mealSlots(mealsPerDay).size

    fun scheduleSlots(
        weekStart: LocalDate,
        days: Int,
        mealsPerDay: Int,
    ): List<MealScheduleSlot> = buildList {
        repeat(days.coerceIn(1, 14)) { dayIndex ->
            val date = weekStart.plusDays(dayIndex.toLong()).toString()
            mealSlots(mealsPerDay).forEach { mealType -> add(MealScheduleSlot(date, mealType)) }
        }
    }

    fun nextWeekStart(today: LocalDate = LocalDate.now()): LocalDate =
        today.with(TemporalAdjusters.nextOrSame(DayOfWeek.MONDAY))

    /** Returns a virtual pantry after reserving ingredients for meals that have not been cooked yet. */
    fun remainingPantry(
        pantry: List<PantryItem>,
        plannedMeals: List<MealProposal>,
    ): List<PantryItem> {
        val reservedByLot = plannedMeals
            .flatMap { it.allocations }
            .groupBy { it.lotId }
            .mapValues { (_, allocations) -> allocations.sumOf { it.quantityMilli } }
        return pantry.mapNotNull { item ->
            val remaining = item.quantityMilli - reservedByLot.getOrDefault(item.id, 0L)
            require(remaining >= 0L) { "A weekly meal tried to reserve more ${item.name} than is available." }
            item.copy(quantityMilli = remaining).takeIf { remaining > 0L }
        }
    }

    fun combinedMissing(meals: List<MealProposal>): List<MealIngredient> = meals
        .flatMap { it.missingIngredients }
        .groupBy { IndianIngredientCatalog.canonicalKey(it.name) to it.unit }
        .map { (_, ingredients) ->
            ingredients.first().copy(quantityMilli = ingredients.sumOf { it.quantityMilli })
        }
        .sortedBy { it.name.lowercase() }

    fun reconcileSchedule(
        meals: List<MealProposal>,
        pantry: List<PantryItem>,
        requestedServings: Int,
        maxMinutes: Int,
        today: LocalDate = LocalDate.now(),
    ): List<MealProposal> {
        val eligible = MealPlanningPolicy.eligiblePantry(pantry, today)
        val reconciled = mutableListOf<MealProposal>()
        meals.forEach { meal ->
            val remaining = remainingPantry(eligible, reconciled)
            reconciled += MealPlanningPolicy.reconcile(
                meal = meal,
                pantry = remaining,
                requiredItem = null,
                requestedServings = requestedServings,
                maxMinutes = maxMinutes,
                today = today,
            )
        }
        MealPlanningPolicy.requiredExpiryItem(eligible, today)?.let { earliest ->
            require(reconciled.any { meal -> meal.allocations.any { it.lotId == earliest.id } }) {
                "The schedule skipped ${earliest.name}, the earliest-expiring pantry item. Try another plan."
            }
        }
        return reconciled
    }
}

object WeeklyMealPrompt {
    private val gson = Gson()

    fun create(
        pantry: List<PantryItem>,
        servings: Int,
        maxMinutes: Int,
        preference: String,
        schedule: List<MealScheduleSlot>,
    ): String {
        require(schedule.isNotEmpty()) { "A schedule needs at least one meal slot." }
        val inventory = MealPlanningPolicy.eligiblePantry(pantry).map {
            mapOf(
                "name" to it.name,
                "quantity" to it.quantityText,
                "unit" to it.unit,
                "expires_on" to it.expiresOn,
            )
        }
        val slots = schedule.map { mapOf("planned_for" to it.plannedFor, "meal_type" to it.mealType) }
        return """
            You are a practical weekly meal planner. Return the complete schedule in one response.
            Emit the final JSON immediately. Do not analyze, deliberate, explain, or draft the schedule before the JSON.
            Create exactly ${schedule.size} simple meals, one for every requested date and meal type below, with no duplicate or missing slots.
            Every meal must serve exactly $servings people and take no more than $maxMinutes minutes.
            Prefer the earliest-expiring safe pantry items in the earliest meals. Across the complete schedule, do not use more than the listed pantry quantities.
            Ingredients not present in the pantry are allowed because the app will add them to one shopping list.
            Keep the output TL;DR: use a short title, a short cuisine label, no more than 8 essential ingredients with total quantities for all $servings servings, 2 to 3 very short preparation steps, and only a brief safety note when needed.
            Do not add optional garnishes, explanations, rationales, substitutions, serving suggestions, or repeated commentary.
            Keep breakfast appropriate for breakfast, lunch for lunch, and dinner for dinner. Vary the meals and follow the cuisine preference.
            Return exactly one JSON object without Markdown or commentary: {"meals":[...]}. Each meal must contain only planned_for, meal_type, title, cuisine, servings, time_minutes, ingredients, steps, and safety_note.
            Each ingredient must contain name, unit, and quantity. Allowed units are count, each, oz, lb, g, kg, ml, and l. Quantity must be a positive decimal string with at most 3 decimal places.

            Preference: ${preference.ifBlank { "No special preference" }}
            Requested slots: ${gson.toJson(slots)}
            Pantry: ${gson.toJson(inventory)}
        """.trimIndent()
    }
}

object WeeklyMealParser {
    fun parse(
        raw: String,
        provider: String,
        expectedSchedule: List<MealScheduleSlot>,
        requestedServings: Int,
        maxMinutes: Int,
    ): List<MealProposal> {
        require(expectedSchedule.isNotEmpty()) { "A schedule needs at least one meal slot." }
        val root = JsonParser.parseString(MealParser.extractJsonObject(raw)).asJsonObject
        val mealsJson = root.getAsJsonArray("meals")
            ?: throw IllegalArgumentException("The model did not return a meal schedule.")
        require(mealsJson.size() == expectedSchedule.size) {
            "The model returned ${mealsJson.size()} meals instead of ${expectedSchedule.size}."
        }

        val expectedByKey = expectedSchedule.associateBy(::slotKey)
        val parsedByKey = linkedMapOf<String, MealProposal>()
        mealsJson.forEach { element ->
            val item = element.asJsonObject
            val plannedFor = item.get("planned_for")?.asString?.trim().orEmpty()
            require(runCatching { LocalDate.parse(plannedFor) }.isSuccess) {
                "The model returned an invalid meal date."
            }
            val mealType = item.get("meal_type")?.asString?.trim().orEmpty()
            val matchingSlot = expectedByKey[slotKey(MealScheduleSlot(plannedFor, mealType))]
                ?: throw IllegalArgumentException("The model returned an unexpected $mealType slot on $plannedFor.")
            val key = slotKey(matchingSlot)
            require(!parsedByKey.containsKey(key)) { "The model returned a duplicate meal slot." }
            val cuisine = item.get("cuisine")?.asString?.trim().orEmpty()
            require(cuisine.isNotEmpty() && cuisine.length <= 40) { "The model returned an invalid cuisine." }
            val meal = MealParser.parse(item.toString(), provider)
            require(meal.servings == requestedServings) {
                "The meal schedule did not honor the requested serving count."
            }
            require(meal.timeMinutes <= maxMinutes) {
                "The meal schedule exceeded the requested cooking time."
            }
            parsedByKey[key] = meal.copy(
                plannedFor = matchingSlot.plannedFor,
                mealType = matchingSlot.mealType,
                rationale = "$cuisine cuisine",
            )
        }

        return expectedSchedule.map { slot ->
            parsedByKey[slotKey(slot)] ?: throw IllegalArgumentException("The model omitted a meal slot.")
        }
    }

    private fun slotKey(slot: MealScheduleSlot): String =
        "${slot.plannedFor}|${slot.mealType.trim().lowercase()}"
}

package com.lokeshvadlamudi.veggieprep

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.lokeshvadlamudi.veggieprep.ai.GeminiNanoMealAi
import com.lokeshvadlamudi.veggieprep.ai.LiteRtMealAi
import com.lokeshvadlamudi.veggieprep.ai.MealAi
import com.lokeshvadlamudi.veggieprep.ai.MealParser
import com.lokeshvadlamudi.veggieprep.ai.MealPlanningPolicy
import com.lokeshvadlamudi.veggieprep.ai.MealPrompt
import com.lokeshvadlamudi.veggieprep.ai.RemoteOpenAiMealAi
import com.lokeshvadlamudi.veggieprep.ai.WeeklyMealPlanningPolicy
import com.lokeshvadlamudi.veggieprep.data.AiProviderType
import com.lokeshvadlamudi.veggieprep.data.AiSettings
import com.lokeshvadlamudi.veggieprep.data.AiSettingsStore
import com.lokeshvadlamudi.veggieprep.data.LocalStore
import com.lokeshvadlamudi.veggieprep.data.MealProposal
import com.lokeshvadlamudi.veggieprep.data.PantryItem
import com.lokeshvadlamudi.veggieprep.data.ShoppingItem
import com.lokeshvadlamudi.veggieprep.data.WeeklyPlan
import com.lokeshvadlamudi.veggieprep.receipt.ReceiptCandidate
import com.lokeshvadlamudi.veggieprep.receipt.ReceiptDraft
import com.lokeshvadlamudi.veggieprep.receipt.ReceiptOcr
import java.io.File
import java.time.LocalDate
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class AppUiState(
    val pantry: List<PantryItem> = emptyList(),
    val meals: List<MealProposal> = emptyList(),
    val shopping: List<ShoppingItem> = emptyList(),
    val weeklyPlan: WeeklyPlan? = null,
    val receiptDraft: ReceiptDraft? = null,
    val lastReceiptImportId: Long? = null,
    val settings: AiSettings = AiSettings(),
    val hasApiKey: Boolean = false,
    val networkDisclosureRemembered: Boolean = false,
    val busy: Boolean = false,
    val status: String = "",
    val error: String? = null,
)

class MainViewModel(application: Application) : AndroidViewModel(application) {
    private val database = LocalStore(application)
    private val settingsStore = AiSettingsStore(application)
    private val mutableState = MutableStateFlow(AppUiState())
    val state: StateFlow<AppUiState> = mutableState.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch(Dispatchers.IO) {
            val settings = settingsStore.load()
            mutableState.value = mutableState.value.copy(
                pantry = database.listPantry(),
                meals = database.listMeals(),
                shopping = database.listShopping(),
                weeklyPlan = database.latestWeeklyPlan(),
                settings = settings,
                hasApiKey = settingsStore.apiKey().isNotEmpty(),
                networkDisclosureRemembered = settings.provider == AiProviderType.REMOTE_OPENAI &&
                    settingsStore.isNetworkDisclosureRemembered(settings.baseUrl),
            )
        }
    }

    fun addItem(
        name: String,
        quantityText: String,
        unit: String,
        location: String,
        purchasedOn: String,
        expiresOn: String,
        category: String,
    ) {
        val quantity = com.lokeshvadlamudi.veggieprep.data.parseMilli(quantityText)
        if (name.isBlank() || quantity == null || quantity <= 0) {
            showError("Enter an item name and a positive quantity with up to 3 decimal places.")
            return
        }
        if (expiresOn.isNotBlank() && runCatching { LocalDate.parse(expiresOn) }.isFailure) {
            showError("Enter the expiry date as YYYY-MM-DD, or leave it blank.")
            return
        }
        viewModelScope.launch(Dispatchers.IO) {
            runCatching {
                database.addLot(name, quantity, unit, location, purchasedOn, expiresOn, category)
                database.listPantry()
            }.onSuccess { pantry ->
                mutableState.value = mutableState.value.copy(pantry = pantry, error = null)
            }.onFailure { showError(it.safeMessage()) }
        }
    }

    fun useItems(items: List<PantryItem>, quantityText: String, discard: Boolean) {
        if (items.isEmpty()) return
        val quantity = com.lokeshvadlamudi.veggieprep.data.parseMilli(quantityText)
        if (quantity == null || quantity <= 0) {
            showError("Enter a positive quantity with up to 3 decimal places.")
            return
        }
        viewModelScope.launch(Dispatchers.IO) {
            runCatching {
                database.changeQuantityAcrossLots(
                    lotIds = items.map(PantryItem::id),
                    amountMilli = quantity,
                    eventType = if (discard) "DISCARD" else "CONSUME",
                    note = if (discard) "Discarded on phone" else "Used on phone",
                )
                database.listPantry()
            }.onSuccess { pantry ->
                mutableState.value = mutableState.value.copy(pantry = pantry, error = null)
            }.onFailure { showError(it.safeMessage()) }
        }
    }

    fun updateItemDetails(items: List<PantryItem>, name: String, expiresOn: String, icon: String) {
        if (items.isEmpty()) return
        val normalizedName = name.trim()
        if (normalizedName.isEmpty() || normalizedName.length > 200) {
            showError("Enter an item name up to 200 characters.")
            return
        }
        val normalized = expiresOn.trim()
        if (normalized.isNotEmpty() && runCatching { LocalDate.parse(normalized) }.isFailure) {
            showError("Enter the expiry date as YYYY-MM-DD, or clear it.")
            return
        }
        val normalizedIcon = icon.trim()
        if (normalizedIcon.length > 16) {
            showError("Choose one emoji or another short icon.")
            return
        }
        viewModelScope.launch(Dispatchers.IO) {
            runCatching {
                database.updateLotDetails(items.map(PantryItem::id), normalizedName, normalized, normalizedIcon)
                database.listPantry()
            }.onSuccess { pantry ->
                mutableState.value = mutableState.value.copy(
                    pantry = pantry,
                    status = "$normalizedName updated",
                    error = null,
                )
            }.onFailure { showError(it.safeMessage()) }
        }
    }

    fun processReceipt(imageUris: List<Uri>) {
        if (imageUris.isEmpty()) {
            showError("No receipt image was returned.")
            return
        }
        mutableState.value = mutableState.value.copy(
            busy = true,
            status = "Reading receipt on this phone…",
            error = null,
        )
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { ReceiptOcr.read(getApplication(), imageUris) }
                .onSuccess { draft ->
                    mutableState.value = mutableState.value.copy(
                        receiptDraft = draft,
                        busy = false,
                        status = "Review every grocery before importing",
                        error = null,
                    )
                }
                .onFailure { showError(it.safeMessage()) }
        }
    }

    fun updateReceiptCandidate(candidate: ReceiptCandidate) {
        val draft = mutableState.value.receiptDraft ?: return
        mutableState.value = mutableState.value.copy(
            receiptDraft = draft.copy(
                candidates = draft.candidates.map { current ->
                    if (current.id == candidate.id) candidate else current
                },
            ),
            error = null,
        )
    }

    fun dismissReceipt() {
        mutableState.value = mutableState.value.copy(receiptDraft = null, error = null, status = "")
    }

    fun importReceipt() {
        val draft = mutableState.value.receiptDraft ?: return
        mutableState.value = mutableState.value.copy(busy = true, status = "Adding selected groceries…", error = null)
        viewModelScope.launch(Dispatchers.IO) {
            runCatching {
                val result = database.importReceipt(draft)
                result to database.listPantry()
            }.onSuccess { (result, pantry) ->
                mutableState.value = mutableState.value.copy(
                    pantry = pantry,
                    receiptDraft = null,
                    lastReceiptImportId = result.importId,
                    busy = false,
                    status = "${result.addedCount} groceries added to pantry",
                    error = null,
                )
            }.onFailure { showError(it.safeMessage()) }
        }
    }

    fun undoReceiptImport(importId: Long) {
        viewModelScope.launch(Dispatchers.IO) {
            runCatching {
                database.undoReceiptImport(importId)
                database.listPantry()
            }.onSuccess { pantry ->
                mutableState.value = mutableState.value.copy(
                    pantry = pantry,
                    lastReceiptImportId = null,
                    status = "Receipt import undone",
                    error = null,
                )
            }.onFailure { showError(it.safeMessage()) }
        }
    }

    fun reportError(message: String) = showError(message)

    fun saveAiSettings(settings: AiSettings, apiKey: String?) {
        runCatching {
            if (settings.provider == AiProviderType.REMOTE_OPENAI) {
                RemoteOpenAiMealAi(settings.baseUrl, settings.model, apiKey ?: settingsStore.apiKey())
            }
            settingsStore.save(settings, apiKey)
        }.onSuccess {
            val savedSettings = settingsStore.load()
            mutableState.value = mutableState.value.copy(
                settings = savedSettings,
                hasApiKey = settingsStore.apiKey().isNotEmpty(),
                networkDisclosureRemembered = savedSettings.provider == AiProviderType.REMOTE_OPENAI &&
                    settingsStore.isNetworkDisclosureRemembered(savedSettings.baseUrl),
                status = "AI choice saved",
                error = null,
            )
        }.onFailure { showError(it.safeMessage()) }
    }

    fun importModel(uri: Uri, displayName: String) {
        mutableState.value = mutableState.value.copy(busy = true, status = "Copying model to this phone…", error = null)
        viewModelScope.launch(Dispatchers.IO) {
            runCatching {
                val modelDirectory = File(getApplication<Application>().filesDir, "models").apply { mkdirs() }
                val destination = File(modelDirectory, "meal-model.litertlm")
                val temporary = File(modelDirectory, "meal-model.importing")
                getApplication<Application>().contentResolver.openInputStream(uri).use { input ->
                    requireNotNull(input) { "Could not open that model file." }
                    temporary.outputStream().use { output -> input.copyTo(output, bufferSize = 1024 * 1024) }
                }
                if (destination.exists() && !destination.delete()) error("Could not replace the previous model.")
                if (!temporary.renameTo(destination)) error("Could not finish importing the model.")
                settingsStore.load().copy(
                    provider = AiProviderType.ON_DEVICE_MODEL,
                    modelPath = destination.absolutePath,
                    modelDisplayName = displayName.ifBlank { "On-device model" },
                )
            }.onSuccess { settings ->
                settingsStore.save(settings, apiKey = null)
                mutableState.value = mutableState.value.copy(
                    settings = settings,
                    networkDisclosureRemembered = false,
                    busy = false,
                    status = "Model ready on this phone",
                    error = null,
                )
            }.onFailure {
                File(getApplication<Application>().filesDir, "models/meal-model.importing").delete()
                mutableState.value = mutableState.value.copy(busy = false, error = it.safeMessage())
            }
        }
    }

    fun generateMeal(
        servings: Int,
        maxMinutes: Int,
        preference: String,
        networkDisclosureConfirmed: Boolean,
        rememberNetworkDisclosure: Boolean,
    ) {
        val snapshot = mutableState.value
        if (snapshot.pantry.isEmpty()) {
            showError("Add at least one pantry item before generating a meal.")
            return
        }
        val settings = settingsStore.load()
        val eligiblePantry = MealPlanningPolicy.eligiblePantry(snapshot.pantry)
        if (eligiblePantry.isEmpty()) {
            showError("All pantry items are expired. Discard or replace them before planning a meal.")
            return
        }
        val requiredItem = MealPlanningPolicy.requiredExpiryItem(eligiblePantry)
        val disclosureRemembered = settings.provider == AiProviderType.REMOTE_OPENAI &&
            settingsStore.isNetworkDisclosureRemembered(settings.baseUrl)
        if (
            settings.provider == AiProviderType.REMOTE_OPENAI &&
            !disclosureRemembered &&
            !networkDisclosureConfirmed
        ) {
            showError("Review and confirm what will be sent to the network AI.")
            return
        }
        val remoteChoiceMade = settings.provider == AiProviderType.REMOTE_OPENAI &&
            networkDisclosureConfirmed
        if (remoteChoiceMade) {
            if (rememberNetworkDisclosure) settingsStore.rememberNetworkDisclosure(settings.baseUrl)
            else settingsStore.forgetNetworkDisclosure(settings.baseUrl)
        }
        val disclosureRememberedAfterChoice = if (remoteChoiceMade) {
            rememberNetworkDisclosure
        } else {
            disclosureRemembered
        }
        mutableState.value = snapshot.copy(
            busy = true,
            status = "Planning a meal…",
            error = null,
            networkDisclosureRemembered = disclosureRememberedAfterChoice,
        )
        viewModelScope.launch {
            runCatching {
                val provider = providerFor(settings)
                val prompt = MealPrompt.create(eligiblePantry, servings, maxMinutes, preference, requiredItem)
                val raw = provider.generate(prompt)
                val proposal = MealParser.parse(raw, provider.label)
                val reconciled = MealPlanningPolicy.reconcile(
                    meal = proposal,
                    pantry = eligiblePantry,
                    requiredItem = requiredItem,
                    requestedServings = servings,
                    maxMinutes = maxMinutes,
                )
                withContext(Dispatchers.IO) {
                    database.saveMeal(reconciled)
                    database.listMeals()
                }
            }.onSuccess { meals ->
                mutableState.value = mutableState.value.copy(
                    meals = meals,
                    busy = false,
                    status = "Meal suggestion saved",
                    error = null,
                )
            }.onFailure {
                mutableState.value = mutableState.value.copy(busy = false, status = "", error = it.safeMessage())
            }
        }
    }

    fun generateWeeklyPlan(
        servings: Int,
        maxMinutes: Int,
        preference: String,
        networkDisclosureConfirmed: Boolean,
        rememberNetworkDisclosure: Boolean,
    ) {
        val snapshot = mutableState.value
        if (snapshot.pantry.isEmpty()) {
            showError("Add at least one pantry item before planning the week.")
            return
        }
        val settings = settingsStore.load()
        val eligiblePantry = MealPlanningPolicy.eligiblePantry(snapshot.pantry)
        if (eligiblePantry.isEmpty()) {
            showError("All pantry items are expired. Discard or replace them before planning the week.")
            return
        }
        val disclosureRemembered = settings.provider == AiProviderType.REMOTE_OPENAI &&
            settingsStore.isNetworkDisclosureRemembered(settings.baseUrl)
        if (settings.provider == AiProviderType.REMOTE_OPENAI && !disclosureRemembered && !networkDisclosureConfirmed) {
            showError("Review and confirm what will be sent to the network AI.")
            return
        }
        val remoteChoiceMade = settings.provider == AiProviderType.REMOTE_OPENAI && networkDisclosureConfirmed
        if (remoteChoiceMade) {
            if (rememberNetworkDisclosure) settingsStore.rememberNetworkDisclosure(settings.baseUrl)
            else settingsStore.forgetNetworkDisclosure(settings.baseUrl)
        }
        mutableState.value = snapshot.copy(
            busy = true,
            status = "Planning meal 1 of ${WeeklyMealPlanningPolicy.DEFAULT_MEAL_COUNT}…",
            error = null,
            networkDisclosureRemembered = if (remoteChoiceMade) rememberNetworkDisclosure else disclosureRemembered,
        )
        viewModelScope.launch {
            runCatching {
                val provider = providerFor(settings)
                val weekStart = WeeklyMealPlanningPolicy.nextWeekStart()
                val plannedMeals = mutableListOf<MealProposal>()
                repeat(WeeklyMealPlanningPolicy.DEFAULT_MEAL_COUNT) { index ->
                    mutableState.value = mutableState.value.copy(
                        status = "Planning meal ${index + 1} of ${WeeklyMealPlanningPolicy.DEFAULT_MEAL_COUNT}…",
                    )
                    val virtualPantry = WeeklyMealPlanningPolicy.remainingPantry(eligiblePantry, plannedMeals)
                    val requiredItem = MealPlanningPolicy.requiredExpiryItem(virtualPantry)
                    val diversity = plannedMeals.joinToString { it.title }.takeIf { it.isNotBlank() }
                    val dayPreference = buildString {
                        append(preference.ifBlank { "No special preference" })
                        append(". This is meal ${index + 1} of a weekday plan.")
                        diversity?.let { append(" Avoid repeating these earlier meals: $it.") }
                    }
                    val prompt = MealPrompt.create(virtualPantry, servings, maxMinutes, dayPreference, requiredItem)
                    val raw = provider.generate(prompt)
                    val proposal = MealParser.parse(raw, provider.label)
                    plannedMeals += MealPlanningPolicy.reconcile(
                        meal = proposal,
                        pantry = virtualPantry,
                        requiredItem = requiredItem,
                        requestedServings = servings,
                        maxMinutes = maxMinutes,
                    ).copy(plannedFor = weekStart.plusDays(index.toLong()).toString())
                }
                val plan = WeeklyPlan(
                    weekStart = weekStart.toString(),
                    servings = servings,
                    maxMinutes = maxMinutes,
                    preference = preference,
                    provider = provider.label,
                )
                withContext(Dispatchers.IO) {
                    database.saveWeeklyPlan(plan, plannedMeals)
                    database.latestWeeklyPlan() to database.listMeals()
                }
            }.onSuccess { (plan, meals) ->
                mutableState.value = mutableState.value.copy(
                    weeklyPlan = plan,
                    meals = meals,
                    busy = false,
                    status = "Next week's meal plan is ready",
                    error = null,
                )
            }.onFailure {
                mutableState.value = mutableState.value.copy(busy = false, status = "", error = it.safeMessage())
            }
        }
    }

    fun addWeeklyMissingToShopping() {
        val plan = mutableState.value.weeklyPlan ?: run {
            showError("Create a weekly plan first.")
            return
        }
        val plannedMeals = mutableState.value.meals.filter { it.planId == plan.id }
        val missing = WeeklyMealPlanningPolicy.combinedMissing(plannedMeals)
        if (missing.isEmpty()) {
            showError("This weekly plan has no missing ingredients.")
            return
        }
        viewModelScope.launch(Dispatchers.IO) {
            runCatching {
                database.addShoppingItems(missing)
                database.listShopping()
            }.onSuccess { shopping ->
                mutableState.value = mutableState.value.copy(
                    shopping = shopping,
                    status = "Weekly ingredients added to shopping",
                    error = null,
                )
            }.onFailure { showError(it.safeMessage()) }
        }
    }

    fun cookMeal(meal: MealProposal) {
        viewModelScope.launch(Dispatchers.IO) {
            runCatching {
                database.cookMeal(meal.id)
                database.listPantry() to database.listMeals()
            }.onSuccess { (pantry, meals) ->
                mutableState.value = mutableState.value.copy(
                    pantry = pantry,
                    meals = meals,
                    status = "Meal cooked and pantry quantities updated",
                    error = null,
                )
            }.onFailure { showError(it.safeMessage()) }
        }
    }

    fun addMissingToShopping(meal: MealProposal) {
        if (meal.missingIngredients.isEmpty()) {
            showError("This meal has no missing ingredients.")
            return
        }
        viewModelScope.launch(Dispatchers.IO) {
            runCatching {
                database.addShoppingItems(meal.missingIngredients)
                database.listShopping()
            }.onSuccess { shopping ->
                mutableState.value = mutableState.value.copy(
                    shopping = shopping,
                    status = "Missing ingredients added to shopping",
                    error = null,
                )
            }.onFailure { showError(it.safeMessage()) }
        }
    }

    fun setShoppingChecked(item: ShoppingItem, checked: Boolean) {
        viewModelScope.launch(Dispatchers.IO) {
            runCatching {
                database.setShoppingChecked(item.id, checked)
                database.listShopping()
            }.onSuccess { shopping ->
                mutableState.value = mutableState.value.copy(shopping = shopping, error = null)
            }.onFailure { showError(it.safeMessage()) }
        }
    }

    fun clearCheckedShopping() {
        viewModelScope.launch(Dispatchers.IO) {
            runCatching {
                database.clearCheckedShopping()
                database.listShopping()
            }.onSuccess { shopping ->
                mutableState.value = mutableState.value.copy(
                    shopping = shopping,
                    status = "Purchased items cleared",
                    error = null,
                )
            }.onFailure { showError(it.safeMessage()) }
        }
    }

    fun clearMessage() {
        mutableState.value = mutableState.value.copy(error = null, status = "", lastReceiptImportId = null)
    }

    private fun providerFor(settings: AiSettings): MealAi = when (settings.provider) {
        AiProviderType.REMOTE_OPENAI -> RemoteOpenAiMealAi(
            settings.baseUrl,
            settings.model,
            settingsStore.apiKey(),
        )
        AiProviderType.GEMINI_NANO -> GeminiNanoMealAi()
        AiProviderType.ON_DEVICE_MODEL -> LiteRtMealAi(
            getApplication(),
            settings.modelPath,
            settings.modelDisplayName.ifBlank { "On-device model" },
        )
    }

    private fun showError(message: String) {
        mutableState.value = mutableState.value.copy(error = message, busy = false)
    }

    override fun onCleared() {
        database.close()
        super.onCleared()
    }
}

private fun Throwable.safeMessage(): String = when (this) {
    is IllegalArgumentException, is IllegalStateException -> message ?: "That operation could not be completed."
    else -> "That operation could not be completed. ${message.orEmpty()}".trim()
}

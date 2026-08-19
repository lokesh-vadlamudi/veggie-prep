package com.lokeshvadlamudi.veggieprep

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.lokeshvadlamudi.veggieprep.ai.GeminiNanoMealAi
import com.lokeshvadlamudi.veggieprep.ai.LiteRtMealAi
import com.lokeshvadlamudi.veggieprep.ai.MealAi
import com.lokeshvadlamudi.veggieprep.ai.MealParser
import com.lokeshvadlamudi.veggieprep.ai.MealPrompt
import com.lokeshvadlamudi.veggieprep.ai.RemoteOpenAiMealAi
import com.lokeshvadlamudi.veggieprep.data.AiProviderType
import com.lokeshvadlamudi.veggieprep.data.AiSettings
import com.lokeshvadlamudi.veggieprep.data.AiSettingsStore
import com.lokeshvadlamudi.veggieprep.data.LocalStore
import com.lokeshvadlamudi.veggieprep.data.MealProposal
import com.lokeshvadlamudi.veggieprep.data.PantryItem
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
    val settings: AiSettings = AiSettings(),
    val hasApiKey: Boolean = false,
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
                settings = settings,
                hasApiKey = settingsStore.apiKey().isNotEmpty(),
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
                database.addLot(name, quantity, unit, location, purchasedOn, expiresOn)
                database.listPantry()
            }.onSuccess { pantry ->
                mutableState.value = mutableState.value.copy(pantry = pantry, error = null)
            }.onFailure { showError(it.safeMessage()) }
        }
    }

    fun useItem(item: PantryItem, quantityText: String, discard: Boolean) {
        val quantity = com.lokeshvadlamudi.veggieprep.data.parseMilli(quantityText)
        if (quantity == null || quantity <= 0) {
            showError("Enter a positive quantity with up to 3 decimal places.")
            return
        }
        viewModelScope.launch(Dispatchers.IO) {
            runCatching {
                database.changeQuantity(
                    lotId = item.id,
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

    fun saveAiSettings(settings: AiSettings, apiKey: String?) {
        runCatching {
            if (settings.provider == AiProviderType.REMOTE_OPENAI) {
                RemoteOpenAiMealAi(settings.baseUrl, settings.model, apiKey ?: settingsStore.apiKey())
            }
            settingsStore.save(settings, apiKey)
        }.onSuccess {
            mutableState.value = mutableState.value.copy(
                settings = settingsStore.load(),
                hasApiKey = settingsStore.apiKey().isNotEmpty(),
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

    fun generateMeal(servings: Int, maxMinutes: Int, preference: String) {
        val snapshot = mutableState.value
        if (snapshot.pantry.isEmpty()) {
            showError("Add at least one pantry item before generating a meal.")
            return
        }
        mutableState.value = snapshot.copy(busy = true, status = "Planning a meal…", error = null)
        viewModelScope.launch {
            runCatching {
                val provider = providerFor(settingsStore.load())
                val prompt = MealPrompt.create(snapshot.pantry, servings, maxMinutes, preference)
                val raw = provider.generate(prompt)
                val proposal = MealParser.parse(raw, provider.label)
                withContext(Dispatchers.IO) {
                    database.saveMeal(proposal)
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

    fun clearMessage() {
        mutableState.value = mutableState.value.copy(error = null, status = "")
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

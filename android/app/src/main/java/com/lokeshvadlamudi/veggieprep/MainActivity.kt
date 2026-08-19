package com.lokeshvadlamudi.veggieprep

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.lokeshvadlamudi.veggieprep.data.AiProviderType
import com.lokeshvadlamudi.veggieprep.data.AiSettings
import com.lokeshvadlamudi.veggieprep.data.MealProposal
import com.lokeshvadlamudi.veggieprep.data.PantryItem
import java.time.LocalDate

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            VeggiePrepTheme {
                val viewModel: MainViewModel = viewModel()
                VeggiePrepApp(viewModel)
            }
        }
    }
}

private enum class AppSection(val label: String) {
    PANTRY("Pantry"),
    MEALS("Meals"),
    AI("AI Choice"),
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun VeggiePrepApp(viewModel: MainViewModel) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    var section by rememberSaveable { mutableStateOf(AppSection.PANTRY) }
    val snackbar = remember { SnackbarHostState() }

    LaunchedEffect(state.error, state.status) {
        val message = state.error ?: state.status.takeIf { it.isNotBlank() }
        if (message != null) {
            snackbar.showSnackbar(message)
            viewModel.clearMessage()
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("Veggie Prep", fontWeight = FontWeight.Bold)
                        Text(section.label, style = MaterialTheme.typography.labelMedium)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Cream),
            )
        },
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            NavigationBar(containerColor = Color.White) {
                NavigationBarItem(
                    selected = section == AppSection.PANTRY,
                    onClick = { section = AppSection.PANTRY },
                    icon = { Icon(Icons.Default.Inventory2, null) },
                    label = { Text("Pantry") },
                )
                NavigationBarItem(
                    selected = section == AppSection.MEALS,
                    onClick = { section = AppSection.MEALS },
                    icon = { Icon(Icons.Default.AutoAwesome, null) },
                    label = { Text("Meals") },
                )
                NavigationBarItem(
                    selected = section == AppSection.AI,
                    onClick = { section = AppSection.AI },
                    icon = { Icon(Icons.Default.Settings, null) },
                    label = { Text("AI Choice") },
                )
            }
        },
        floatingActionButton = {
            if (state.busy) FloatingActionButton(onClick = {}, containerColor = Color.White) {
                CircularProgressIndicator(modifier = Modifier.width(28.dp))
            }
        },
        containerColor = Cream,
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when (section) {
                AppSection.PANTRY -> PantryScreen(state.pantry, viewModel::addItem, viewModel::useItem)
                AppSection.MEALS -> MealsScreen(state, viewModel::generateMeal) { section = AppSection.AI }
                AppSection.AI -> AiSettingsScreen(state, viewModel::saveAiSettings, viewModel::importModel)
            }
        }
    }
}

@Composable
private fun PantryScreen(
    pantry: List<PantryItem>,
    onAdd: (String, String, String, String, String, String) -> Unit,
    onUse: (PantryItem, String, Boolean) -> Unit,
) {
    var showAdd by rememberSaveable { mutableStateOf(false) }
    var actionItem by remember { mutableStateOf<PantryItem?>(null) }
    var discard by remember { mutableStateOf(false) }

    Box(Modifier.fillMaxSize()) {
        if (pantry.isEmpty()) {
            EmptyState(
                title = "Your pantry lives on this phone",
                detail = "Add vegetables and staples. No account or server is needed.",
                button = "Add first item",
                onClick = { showAdd = true },
            )
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp, 12.dp, 16.dp, 96.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                item { Text("Use soon", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold) }
                items(pantry, key = { it.id }) { item ->
                    PantryCard(
                        item = item,
                        onUse = { actionItem = item; discard = false },
                        onDiscard = { actionItem = item; discard = true },
                    )
                }
            }
        }
        FloatingActionButton(
            onClick = { showAdd = true },
            modifier = Modifier.align(Alignment.BottomEnd).padding(20.dp),
            containerColor = Leaf,
            contentColor = Color.White,
        ) { Text("+", style = MaterialTheme.typography.headlineMedium) }
    }

    if (showAdd) AddItemDialog(onDismiss = { showAdd = false }) { name, quantity, unit, location, purchased, expires ->
        onAdd(name, quantity, unit, location, purchased, expires)
        showAdd = false
    }
    actionItem?.let { item ->
        QuantityDialog(
            item = item,
            discard = discard,
            onDismiss = { actionItem = null },
            onConfirm = { quantity -> onUse(item, quantity, discard); actionItem = null },
        )
    }
}

@Composable
private fun PantryCard(item: PantryItem, onUse: () -> Unit, onDiscard: () -> Unit) {
    Card(colors = CardDefaults.cardColors(containerColor = Color.White), shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(item.name, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
                Text("${item.quantityText} ${item.unit}", color = Leaf, fontWeight = FontWeight.Bold)
            }
            Text(buildString {
                append(item.location.replaceFirstChar(Char::uppercase))
                item.expiresOn?.let { append("  •  Expires $it") }
            }, color = Muted)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onUse) { Text("Use") }
                TextButton(onClick = onDiscard) { Text("Discard", color = Danger) }
            }
        }
    }
}

@Composable
private fun AddItemDialog(
    onDismiss: () -> Unit,
    onConfirm: (String, String, String, String, String, String) -> Unit,
) {
    var name by rememberSaveable { mutableStateOf("") }
    var quantity by rememberSaveable { mutableStateOf("") }
    var unit by rememberSaveable { mutableStateOf("count") }
    var location by rememberSaveable { mutableStateOf("fridge") }
    var expires by rememberSaveable { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Add to pantry") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(name, { name = it }, label = { Text("Item") }, singleLine = true)
                OutlinedTextField(
                    quantity,
                    { quantity = it },
                    label = { Text("Quantity") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    singleLine = true,
                )
                Text("Unit", style = MaterialTheme.typography.labelLarge)
                ChoiceRow(listOf("count", "each", "g", "kg", "ml", "l"), unit) { unit = it }
                Text("Stored in", style = MaterialTheme.typography.labelLarge)
                ChoiceRow(listOf("fridge", "pantry", "freezer"), location) { location = it }
                OutlinedTextField(expires, { expires = it }, label = { Text("Expiry date (YYYY-MM-DD, optional)") }, singleLine = true)
            }
        },
        confirmButton = { Button(onClick = { onConfirm(name, quantity, unit, location, LocalDate.now().toString(), expires) }) { Text("Add") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun ChoiceRow(options: List<String>, selected: String, onSelect: (String) -> Unit) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        options.forEach { option ->
            AssistChip(onClick = { onSelect(option) }, label = { Text(if (option == selected) "✓ $option" else option) })
        }
    }
}

@Composable
private fun QuantityDialog(item: PantryItem, discard: Boolean, onDismiss: () -> Unit, onConfirm: (String) -> Unit) {
    var quantity by rememberSaveable { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (discard) "Discard ${item.name}" else "Use ${item.name}") },
        text = {
            OutlinedTextField(
                quantity,
                { quantity = it },
                label = { Text("Quantity (${item.unit})") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                singleLine = true,
            )
        },
        confirmButton = { Button(onClick = { onConfirm(quantity) }) { Text(if (discard) "Discard" else "Use") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun MealsScreen(state: AppUiState, onGenerate: (Int, Int, String) -> Unit, openSettings: () -> Unit) {
    var servingsText by rememberSaveable { mutableStateOf("2") }
    var minutesText by rememberSaveable { mutableStateOf("45") }
    var preference by rememberSaveable { mutableStateOf("") }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp, 12.dp, 16.dp, 32.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Card(colors = CardDefaults.cardColors(containerColor = Color.White), shape = RoundedCornerShape(18.dp)) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("Plan from your pantry", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                    Text("Using ${providerLabel(state.settings)}. Your pantry stays on the phone unless you choose a network API.", color = Muted)
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        OutlinedTextField(
                            servingsText, { servingsText = it }, label = { Text("Servings") },
                            modifier = Modifier.weight(1f), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), singleLine = true,
                        )
                        OutlinedTextField(
                            minutesText, { minutesText = it }, label = { Text("Max minutes") },
                            modifier = Modifier.weight(1f), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), singleLine = true,
                        )
                    }
                    OutlinedTextField(preference, { preference = it }, label = { Text("Preference (optional)") }, modifier = Modifier.fillMaxWidth())
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(
                            onClick = { onGenerate(servingsText.toIntOrNull()?.coerceIn(1, 20) ?: 2, minutesText.toIntOrNull()?.coerceIn(5, 360) ?: 45, preference) },
                            enabled = !state.busy,
                        ) { Text("Suggest a meal") }
                        OutlinedButton(onClick = openSettings) { Text("Change AI") }
                    }
                }
            }
        }
        if (state.meals.isEmpty()) {
            item { Text("Generated meals will be saved here on this phone.", color = Muted, modifier = Modifier.padding(8.dp)) }
        } else {
            item { Text("Saved meals", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold) }
            items(state.meals, key = { it.id }) { MealCard(it) }
        }
    }
}

@Composable
private fun MealCard(meal: MealProposal) {
    Card(colors = CardDefaults.cardColors(containerColor = Color.White), shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(meal.title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text("${meal.servings} servings  •  ${meal.timeMinutes} min  •  ${meal.provider}", color = Muted)
            if (meal.rationale.isNotBlank()) Text(meal.rationale)
            Text("Ingredients", fontWeight = FontWeight.SemiBold)
            meal.ingredients.forEach { Text("• ${it.name}: ${com.lokeshvadlamudi.veggieprep.data.formatMilli(it.quantityMilli)} ${it.unit}") }
            Text("Steps", fontWeight = FontWeight.SemiBold)
            meal.steps.forEachIndexed { index, step -> Text("${index + 1}. $step") }
            if (meal.safetyNote.isNotBlank()) Text("Safety: ${meal.safetyNote}", color = Danger)
        }
    }
}

@Composable
private fun AiSettingsScreen(
    state: AppUiState,
    onSave: (AiSettings, String?) -> Unit,
    onImport: (android.net.Uri, String) -> Unit,
) {
    var provider by rememberSaveable { mutableStateOf(state.settings.provider) }
    var baseUrl by rememberSaveable { mutableStateOf(state.settings.baseUrl) }
    var model by rememberSaveable { mutableStateOf(state.settings.model) }
    var apiKey by rememberSaveable { mutableStateOf("") }
    val modelPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri?.let { onImport(it, it.lastPathSegment?.substringAfterLast('/') ?: "Imported model") }
    }
    LaunchedEffect(state.settings) {
        provider = state.settings.provider
        baseUrl = state.settings.baseUrl
        model = state.settings.model
    }

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Choose how meals are generated", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Text("Pantry data remains local unless you select a network API and ask it to generate a meal.", color = Muted)

        ProviderCard(
            selected = provider == AiProviderType.GEMINI_NANO,
            title = "Gemini Nano on this phone",
            detail = "No API key or network during generation. Available only on supported Android devices.",
            onClick = { provider = AiProviderType.GEMINI_NANO },
        )
        ProviderCard(
            selected = provider == AiProviderType.ON_DEVICE_MODEL,
            title = "Gemma or another phone model",
            detail = if (state.settings.modelPath.isBlank()) "Import a .litertlm model file." else "Ready: ${state.settings.modelDisplayName}",
            onClick = { provider = AiProviderType.ON_DEVICE_MODEL },
        )
        if (provider == AiProviderType.ON_DEVICE_MODEL) {
            OutlinedButton(
                onClick = { modelPicker.launch(arrayOf("application/octet-stream", "application/zip", "*/*")) },
                enabled = !state.busy,
                modifier = Modifier.fillMaxWidth(),
            ) { Text(if (state.settings.modelPath.isBlank()) "Import model" else "Replace model") }
            Text("Models are large and are copied into private app storage. Gemma 3 1B or Gemma 3n variants optimized as .litertlm are suitable starting points.", style = MaterialTheme.typography.bodySmall, color = Muted)
        }

        ProviderCard(
            selected = provider == AiProviderType.REMOTE_OPENAI,
            title = "Local IP or OpenAI-compatible API",
            detail = "Works with vLLM, Ollama-compatible gateways, your DGX, or an HTTPS API.",
            onClick = { provider = AiProviderType.REMOTE_OPENAI },
        )
        if (provider == AiProviderType.REMOTE_OPENAI) {
            OutlinedTextField(
                baseUrl, { baseUrl = it }, label = { Text("API base URL") },
                placeholder = { Text("http://100.x.x.x:8000/v1") }, modifier = Modifier.fillMaxWidth(), singleLine = true,
            )
            OutlinedTextField(
                model, { model = it }, label = { Text("Model name") },
                placeholder = { Text("qwen3.5 or gpt-5-mini") }, modifier = Modifier.fillMaxWidth(), singleLine = true,
            )
            OutlinedTextField(
                apiKey, { apiKey = it }, label = { Text(if (state.hasApiKey) "API key (saved; leave blank to keep)" else "API key (optional for local models)") },
                visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth(), singleLine = true,
            )
            Text("HTTP is accepted only for private Wi‑Fi, .local, loopback, or Tailscale addresses. Public APIs must use HTTPS.", style = MaterialTheme.typography.bodySmall, color = Muted)
        }

        Button(
            onClick = {
                val next = state.settings.copy(provider = provider, baseUrl = baseUrl, model = model)
                onSave(next, apiKey.takeIf { it.isNotBlank() })
            },
            enabled = !state.busy,
            modifier = Modifier.fillMaxWidth(),
        ) { Text("Save AI choice") }
        Spacer(Modifier.height(20.dp))
    }
}

@Composable
private fun ProviderCard(selected: Boolean, title: String, detail: String, onClick: () -> Unit) {
    Card(
        onClick = onClick,
        colors = CardDefaults.cardColors(containerColor = if (selected) PaleGreen else Color.White),
        shape = RoundedCornerShape(18.dp),
    ) {
        Row(Modifier.fillMaxWidth().padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            RadioButton(selected = selected, onClick = onClick)
            Spacer(Modifier.width(8.dp))
            Column {
                Text(title, fontWeight = FontWeight.SemiBold)
                Text(detail, style = MaterialTheme.typography.bodySmall, color = Muted)
            }
        }
    }
}

@Composable
private fun EmptyState(title: String, detail: String, button: String, onClick: () -> Unit) {
    Column(
        Modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("🌿", style = MaterialTheme.typography.displayMedium)
        Spacer(Modifier.height(16.dp))
        Text(title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(8.dp))
        Text(detail, color = Muted)
        Spacer(Modifier.height(18.dp))
        Button(onClick = onClick) { Text(button) }
    }
}

private fun providerLabel(settings: AiSettings): String = when (settings.provider) {
    AiProviderType.GEMINI_NANO -> "Gemini Nano on this phone"
    AiProviderType.ON_DEVICE_MODEL -> settings.modelDisplayName.ifBlank { "an imported phone model" }
    AiProviderType.REMOTE_OPENAI -> settings.model.ifBlank { "an OpenAI-compatible API" }
}

private val Cream = Color(0xFFF5F2E9)
private val Leaf = Color(0xFF2E7D32)
private val PaleGreen = Color(0xFFE5F2E3)
private val Muted = Color(0xFF5D6B61)
private val Danger = Color(0xFFC0281D)

@Composable
private fun VeggiePrepTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = androidx.compose.material3.lightColorScheme(
            primary = Leaf,
            onPrimary = Color.White,
            secondary = Color(0xFF7CB545),
            background = Cream,
            surface = Color.White,
            error = Danger,
        ),
        content = content,
    )
}

package com.lokeshvadlamudi.veggieprep

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
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
import androidx.compose.material.icons.filled.ShoppingCart
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
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
import com.lokeshvadlamudi.veggieprep.data.CatalogIngredient
import com.lokeshvadlamudi.veggieprep.data.IndianIngredientCatalog
import com.lokeshvadlamudi.veggieprep.data.MealProposal
import com.lokeshvadlamudi.veggieprep.data.MealStatus
import com.lokeshvadlamudi.veggieprep.data.PantryItem
import com.lokeshvadlamudi.veggieprep.data.ShoppingItem
import com.lokeshvadlamudi.veggieprep.data.formatMilli
import com.lokeshvadlamudi.veggieprep.ai.MealPlanningPolicy
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
    SNACKS("Snacks"),
    MEALS("Meals"),
    SHOPPING("Shopping"),
    AI("AI Choice"),
}

private data class PendingMealRequest(
    val servings: Int,
    val maxMinutes: Int,
    val preference: String,
)

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
                    selected = section == AppSection.SNACKS,
                    onClick = { section = AppSection.SNACKS },
                    icon = { Text("🍿", style = MaterialTheme.typography.titleLarge) },
                    label = { Text("Snacks") },
                )
                NavigationBarItem(
                    selected = section == AppSection.MEALS,
                    onClick = { section = AppSection.MEALS },
                    icon = { Icon(Icons.Default.AutoAwesome, null) },
                    label = { Text("Meals") },
                )
                NavigationBarItem(
                    selected = section == AppSection.SHOPPING,
                    onClick = { section = AppSection.SHOPPING },
                    icon = { Icon(Icons.Default.ShoppingCart, null) },
                    label = { Text("Shop") },
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
                AppSection.PANTRY -> PantryScreen(
                    pantry = state.pantry,
                    onAdd = viewModel::addItem,
                    onUse = viewModel::useItem,
                    onUpdateExpiry = viewModel::updateExpiry,
                )
                AppSection.SNACKS -> PantryScreen(
                    pantry = state.pantry.filter { IndianIngredientCatalog.isSnack(it.name, it.category) },
                    onAdd = viewModel::addItem,
                    onUse = viewModel::useItem,
                    onUpdateExpiry = viewModel::updateExpiry,
                    heading = "Available snacks",
                    emptyTitle = "No snacks yet",
                    emptyDetail = "Add chips, biscuits, namkeen, sweets, bakery items, or any custom snack.",
                    emptyButton = "Add a snack",
                    snacksOnly = true,
                )
                AppSection.MEALS -> MealsScreen(
                    state = state,
                    onGenerate = viewModel::generateMeal,
                    onCook = viewModel::cookMeal,
                    onAddMissing = {
                        viewModel.addMissingToShopping(it)
                        section = AppSection.SHOPPING
                    },
                    openSettings = { section = AppSection.AI },
                )
                AppSection.SHOPPING -> ShoppingScreen(
                    items = state.shopping,
                    onChecked = viewModel::setShoppingChecked,
                    onClearChecked = viewModel::clearCheckedShopping,
                )
                AppSection.AI -> AiSettingsScreen(state, viewModel::saveAiSettings, viewModel::importModel)
            }
        }
    }
}

@Composable
private fun PantryScreen(
    pantry: List<PantryItem>,
    onAdd: (String, String, String, String, String, String, String) -> Unit,
    onUse: (PantryItem, String, Boolean) -> Unit,
    onUpdateExpiry: (PantryItem, String) -> Unit,
    heading: String = "Use soon",
    emptyTitle: String = "Your pantry lives on this phone",
    emptyDetail: String = "Add vegetables and staples. No account or server is needed.",
    emptyButton: String = "Add first item",
    snacksOnly: Boolean = false,
) {
    var showAdd by rememberSaveable { mutableStateOf(false) }
    var actionItem by remember { mutableStateOf<PantryItem?>(null) }
    var expiryItem by remember { mutableStateOf<PantryItem?>(null) }
    var discard by remember { mutableStateOf(false) }

    Box(Modifier.fillMaxSize()) {
        if (pantry.isEmpty()) {
            EmptyState(
                title = emptyTitle,
                detail = emptyDetail,
                button = emptyButton,
                onClick = { showAdd = true },
            )
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp, 12.dp, 16.dp, 96.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                item { Text(heading, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold) }
                items(pantry, key = { it.id }) { item ->
                    PantryCard(
                        item = item,
                        onUse = { actionItem = item; discard = false },
                        onEditExpiry = { expiryItem = item },
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

    if (showAdd) QuickAddDialog(snacksOnly = snacksOnly, onDismiss = { showAdd = false }) { name, quantity, unit, location, purchased, expires, category ->
        onAdd(name, quantity, unit, location, purchased, expires, category)
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
    expiryItem?.let { item ->
        ExpiryDialog(
            item = item,
            onDismiss = { expiryItem = null },
            onConfirm = { expiry -> onUpdateExpiry(item, expiry); expiryItem = null },
        )
    }
}

@Composable
private fun PantryCard(item: PantryItem, onUse: () -> Unit, onEditExpiry: () -> Unit, onDiscard: () -> Unit) {
    Card(colors = CardDefaults.cardColors(containerColor = Color.White), shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(IndianIngredientCatalog.find(item.name)?.visual ?: "🧺", style = MaterialTheme.typography.headlineMedium)
                    Text(item.name, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
                }
                Text("${item.quantityText} ${item.unit}", color = Leaf, fontWeight = FontWeight.Bold)
            }
            Text(buildString {
                append(item.location.replaceFirstChar(Char::uppercase))
                item.expiresOn?.let { append("  •  Expires $it") }
            }, color = Muted)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onUse) { Text("Use") }
                TextButton(onClick = onEditExpiry) { Text("Edit expiry") }
                TextButton(onClick = onDiscard) { Text("Discard", color = Danger) }
            }
        }
    }
}

@Composable
private fun QuickAddDialog(
    snacksOnly: Boolean,
    onDismiss: () -> Unit,
    onConfirm: (String, String, String, String, String, String, String) -> Unit,
) {
    var query by rememberSaveable { mutableStateOf("") }
    var selected by remember { mutableStateOf<CatalogIngredient?>(null) }
    var custom by rememberSaveable { mutableStateOf(false) }
    var name by rememberSaveable { mutableStateOf("") }
    var quantity by rememberSaveable { mutableStateOf("") }
    var unit by rememberSaveable { mutableStateOf("count") }
    var location by rememberSaveable { mutableStateOf("fridge") }
    var expires by rememberSaveable { mutableStateOf("") }
    val editingDetails = selected != null || custom

    fun choose(ingredient: CatalogIngredient) {
        selected = ingredient
        custom = false
        name = ingredient.name
        quantity = ingredient.defaultQuantity
        unit = ingredient.defaultUnit
        location = ingredient.defaultStorage
        expires = ingredient.suggestedExpiry()
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (editingDetails) "Add ${selected?.name ?: "custom item"}" else if (snacksOnly) "Add a snack" else "Quick add food") },
        text = {
            if (!editingDetails) {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedTextField(
                        query,
                        { query = it },
                        label = { Text(if (snacksOnly) "Search chips, biscuits, namkeen…" else "Search eggs, sourdough, roti, palak…") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                    )
                    Text("Works offline • broad food types and regional aliases", color = Muted, style = MaterialTheme.typography.bodySmall)
                    LazyColumn(
                        modifier = Modifier.heightIn(max = 460.dp),
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        items(
                            IndianIngredientCatalog.search(query)
                                .filter { !snacksOnly || IndianIngredientCatalog.isSnackCategory(it.category) }
                                .take(30),
                            key = { it.id },
                        ) { ingredient ->
                            Card(
                                onClick = { choose(ingredient) },
                                colors = CardDefaults.cardColors(containerColor = PaleGreen),
                            ) {
                                Row(
                                    Modifier.fillMaxWidth().padding(12.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                                ) {
                                    Text(ingredient.visual, style = MaterialTheme.typography.headlineMedium)
                                    Column(Modifier.weight(1f)) {
                                        Text(ingredient.name, fontWeight = FontWeight.SemiBold)
                                        Text(
                                            buildString {
                                                append(ingredient.category)
                                                ingredient.aliases.take(3).takeIf { it.isNotEmpty() }?.let {
                                                    append(" • ${it.joinToString()}")
                                                }
                                            },
                                            color = Muted,
                                            style = MaterialTheme.typography.bodySmall,
                                        )
                                    }
                                }
                            }
                        }
                    }
                    TextButton(
                        onClick = {
                            custom = true
                            selected = null
                            name = query
                            quantity = ""
                            expires = ""
                        },
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text("Add a custom item instead") }
                }
            } else {
                Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    selected?.let {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            Text(it.visual, style = MaterialTheme.typography.displaySmall)
                            Column {
                                Text(it.category, color = Muted)
                                Text(it.aliases.take(4).joinToString(), style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                    if (custom) {
                        OutlinedTextField(name, { name = it }, label = { Text("Item") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                    }
                    OutlinedTextField(
                        quantity,
                        { quantity = it },
                        label = { Text("Quantity") },
                        modifier = Modifier.fillMaxWidth(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                        singleLine = true,
                    )
                    Text("Unit", style = MaterialTheme.typography.labelLarge)
                    ChoiceRow(listOf("count", "each", "g", "kg", "ml", "l"), unit) { unit = it }
                    Text("Stored in", style = MaterialTheme.typography.labelLarge)
                    ChoiceRow(listOf("fridge", "pantry", "freezer"), location) { location = it }
                    OutlinedTextField(
                        expires,
                        { expires = it },
                        label = { Text("Expiry date (YYYY-MM-DD, optional)") },
                        supportingText = { Text("Suggested from typical shelf life; verify the package and freshness.") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                    )
                }
            }
        },
        confirmButton = {
            if (editingDetails) {
                Button(
                    onClick = {
                        val category = selected?.category ?: if (snacksOnly) "Snacks" else "Other"
                        onConfirm(name, quantity, unit, location, LocalDate.now().toString(), expires, category)
                    },
                    enabled = name.isNotBlank() && quantity.isNotBlank(),
                ) { Text("Add") }
            }
        },
        dismissButton = {
            TextButton(
                onClick = {
                    if (editingDetails) {
                        selected = null
                        custom = false
                    } else {
                        onDismiss()
                    }
                },
            ) { Text(if (editingDetails) "Back" else "Cancel") }
        },
    )
}

@Composable
private fun ChoiceRow(options: List<String>, selected: String, onSelect: (String) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        options.chunked(3).forEach { rowOptions ->
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                rowOptions.forEach { option ->
                    AssistChip(
                        onClick = { onSelect(option) },
                        label = { Text(if (option == selected) "✓ $option" else option) },
                    )
                }
            }
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
private fun ExpiryDialog(item: PantryItem, onDismiss: () -> Unit, onConfirm: (String) -> Unit) {
    var expires by rememberSaveable(item.id) { mutableStateOf(item.expiresOn.orEmpty()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Edit ${item.name} expiry") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = expires,
                    onValueChange = { expires = it },
                    label = { Text("Expiry date (YYYY-MM-DD)") },
                    supportingText = { Text("Change the date, or clear it if this item has no known expiry.") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                )
                if (expires.isNotBlank()) {
                    TextButton(onClick = { expires = "" }) { Text("Clear expiry") }
                }
            }
        },
        confirmButton = { Button(onClick = { onConfirm(expires) }) { Text("Save") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun MealsScreen(
    state: AppUiState,
    onGenerate: (Int, Int, String, Boolean, Boolean) -> Unit,
    onCook: (MealProposal) -> Unit,
    onAddMissing: (MealProposal) -> Unit,
    openSettings: () -> Unit,
) {
    var servingsText by rememberSaveable { mutableStateOf("2") }
    var minutesText by rememberSaveable { mutableStateOf("45") }
    var preference by rememberSaveable { mutableStateOf("") }
    var pendingRequest by remember { mutableStateOf<PendingMealRequest?>(null) }
    var rememberNetworkDisclosure by rememberSaveable { mutableStateOf(false) }

    fun requestMeal(forceDisclosure: Boolean = false) {
        val request = PendingMealRequest(
            servings = servingsText.toIntOrNull()?.coerceIn(1, 20) ?: 2,
            maxMinutes = minutesText.toIntOrNull()?.coerceIn(5, 360) ?: 45,
            preference = preference,
        )
        if (state.pantry.isEmpty()) {
            onGenerate(request.servings, request.maxMinutes, request.preference, false, false)
        } else if (
            state.settings.provider == AiProviderType.REMOTE_OPENAI &&
            (forceDisclosure || !state.networkDisclosureRemembered)
        ) {
            rememberNetworkDisclosure = state.networkDisclosureRemembered
            pendingRequest = request
        } else {
            onGenerate(request.servings, request.maxMinutes, request.preference, false, false)
        }
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp, 12.dp, 16.dp, 32.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Card(colors = CardDefaults.cardColors(containerColor = Color.White), shape = RoundedCornerShape(18.dp)) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("Plan from your pantry", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                    if (state.settings.provider == AiProviderType.REMOTE_OPENAI) {
                        Text(
                            "Using ${providerLabel(state.settings)}. Item names, quantities, units, and expiry dates are sent to ${state.settings.baseUrl.ifBlank { "the configured API" }}. Storage locations stay on this phone.",
                            color = Muted,
                        )
                    } else {
                        Text("Using ${providerLabel(state.settings)}. Meal generation stays on this phone.", color = Muted)
                    }
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
                            onClick = { requestMeal() },
                            enabled = !state.busy,
                        ) { Text("Suggest a meal") }
                        OutlinedButton(onClick = openSettings) { Text("Change AI") }
                    }
                    if (state.settings.provider == AiProviderType.REMOTE_OPENAI) {
                        TextButton(onClick = { requestMeal(forceDisclosure = true) }) {
                            Text("Review what will be shared")
                        }
                    }
                }
            }
        }
        if (state.meals.isEmpty()) {
            item { Text("Generated meals will be saved here on this phone.", color = Muted, modifier = Modifier.padding(8.dp)) }
        } else {
            item { Text("Saved meals", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold) }
            items(state.meals, key = { it.id }) { meal ->
                MealCard(meal, onCook = { onCook(meal) }, onAddMissing = { onAddMissing(meal) })
            }
        }
    }

    pendingRequest?.let { request ->
        NetworkMealDisclosureDialog(
            settings = state.settings,
            pantry = state.pantry,
            request = request,
            rememberChoice = rememberNetworkDisclosure,
            onRememberChoiceChange = { rememberNetworkDisclosure = it },
            onDismiss = {
                pendingRequest = null
                rememberNetworkDisclosure = false
            },
            onConfirm = {
                onGenerate(
                    request.servings,
                    request.maxMinutes,
                    request.preference,
                    true,
                    rememberNetworkDisclosure,
                )
                pendingRequest = null
                rememberNetworkDisclosure = false
            },
        )
    }
}

@Composable
private fun NetworkMealDisclosureDialog(
    settings: AiSettings,
    pantry: List<PantryItem>,
    request: PendingMealRequest,
    rememberChoice: Boolean,
    onRememberChoiceChange: (Boolean) -> Unit,
    onDismiss: () -> Unit,
    onConfirm: () -> Unit,
) {
    val sharedPantry = MealPlanningPolicy.eligiblePantry(pantry)
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Send pantry details to network AI?") },
        text = {
            Column(
                Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Text("Destination", fontWeight = FontWeight.SemiBold)
                Text(settings.baseUrl.ifBlank { "Configured network API" }, color = Muted)
                Text("Pantry preview", fontWeight = FontWeight.SemiBold)
                sharedPantry.forEach { item ->
                    Text(
                        buildString {
                            append("• ${item.name}: ${item.quantityText} ${item.unit}")
                            item.expiresOn?.let { append(" · expires $it") }
                        },
                    )
                }
                Text(
                    "Meal request: ${request.servings} servings, up to ${request.maxMinutes} minutes. Preference: ${request.preference.ifBlank { "none" }}.",
                )
                Text(
                    "Expired items, storage locations, purchase dates, and inventory history are not sent. If configured, the API key is sent separately as an authorization header and is never included in the meal prompt.",
                    color = Muted,
                    style = MaterialTheme.typography.bodySmall,
                )
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(
                        checked = rememberChoice,
                        onCheckedChange = onRememberChoiceChange,
                    )
                    Text("Don't ask again for this API address")
                }
            }
        },
        confirmButton = { Button(onClick = onConfirm) { Text("Send and suggest") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun MealCard(
    meal: MealProposal,
    onCook: () -> Unit,
    onAddMissing: () -> Unit,
) {
    var confirmCook by remember { mutableStateOf(false) }
    val rescued = meal.allocations.filter { it.rescued }.map { it.name }.distinct()
    Card(colors = CardDefaults.cardColors(containerColor = Color.White), shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(meal.title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text("${meal.servings} servings  •  ${meal.timeMinutes} min  •  ${meal.provider}", color = Muted)
            if (rescued.isNotEmpty()) {
                Text("Rescues soon: ${rescued.joinToString()}", color = Leaf, fontWeight = FontWeight.SemiBold)
            }
            if (meal.rationale.isNotBlank()) Text(meal.rationale)
            Text("Ingredients", fontWeight = FontWeight.SemiBold)
            meal.ingredients.forEach { Text("• ${it.name}: ${formatMilli(it.quantityMilli)} ${it.unit}") }
            if (meal.missingIngredients.isNotEmpty()) {
                Text("Missing", fontWeight = FontWeight.SemiBold, color = Danger)
                meal.missingIngredients.forEach { Text("• ${it.name}: ${formatMilli(it.quantityMilli)} ${it.unit}") }
                OutlinedButton(onClick = onAddMissing) { Text("Add missing to shopping") }
            }
            Text("Steps", fontWeight = FontWeight.SemiBold)
            meal.steps.forEachIndexed { index, step -> Text("${index + 1}. $step") }
            if (meal.safetyNote.isNotBlank()) Text("Safety: ${meal.safetyNote}", color = Danger)
            when (meal.status) {
                MealStatus.COOKED -> Text("✓ Cooked • pantry updated", color = Leaf, fontWeight = FontWeight.Bold)
                MealStatus.SUGGESTED -> if (meal.allocations.isEmpty()) {
                    Text("Generate a fresh suggestion to enable pantry deduction.", color = Muted)
                } else {
                    Button(onClick = { confirmCook = true }) { Text("Cook & deduct pantry") }
                }
            }
        }
    }

    if (confirmCook) {
        AlertDialog(
            onDismissRequest = { confirmCook = false },
            title = { Text("Cook ${meal.title}?") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("The following quantities will be deducted from the earliest matching pantry lots:")
                    meal.allocations.groupBy { it.name to it.unit }.forEach { (key, values) ->
                        Text("• ${key.first}: ${formatMilli(values.sumOf { it.quantityMilli })} ${key.second}")
                    }
                    if (meal.missingIngredients.isNotEmpty()) {
                        Text("Missing ingredients are not deducted. Confirm that you have handled them separately.", color = Danger)
                    }
                }
            },
            confirmButton = {
                Button(onClick = { confirmCook = false; onCook() }) { Text("Cook and deduct") }
            },
            dismissButton = { TextButton(onClick = { confirmCook = false }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun ShoppingScreen(
    items: List<ShoppingItem>,
    onChecked: (ShoppingItem, Boolean) -> Unit,
    onClearChecked: () -> Unit,
) {
    if (items.isEmpty()) {
        EmptyState(
            title = "Nothing missing",
            detail = "Generate a meal and add its missing ingredients here. Quantities are combined automatically.",
            button = null,
        )
        return
    }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp, 12.dp, 16.dp, 32.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Text("Missing ingredients", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            Text("Built from meal gaps after subtracting pantry quantities.", color = Muted)
        }
        items(items, key = { it.id }) { item ->
            Card(colors = CardDefaults.cardColors(containerColor = Color.White), shape = RoundedCornerShape(18.dp)) {
                Row(
                    Modifier.fillMaxWidth().clickable { onChecked(item, !item.checked) }.padding(12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Checkbox(checked = item.checked, onCheckedChange = { onChecked(item, it) })
                    Text(IndianIngredientCatalog.find(item.name)?.visual ?: "🛒", style = MaterialTheme.typography.headlineMedium)
                    Column(Modifier.weight(1f)) {
                        Text(item.name, fontWeight = FontWeight.SemiBold)
                        Text("${item.quantityText} ${item.unit}", color = Muted)
                    }
                }
            }
        }
        if (items.any { it.checked }) {
            item { TextButton(onClick = onClearChecked) { Text("Clear purchased items") } }
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
    var showPrivacy by rememberSaveable { mutableStateOf(false) }
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
        TextButton(
            onClick = { showPrivacy = true },
            modifier = Modifier.fillMaxWidth(),
        ) { Text("Privacy and data") }
        Spacer(Modifier.height(20.dp))
    }

    if (showPrivacy) {
        AlertDialog(
            onDismissRequest = { showPrivacy = false },
            title = { Text("Privacy and data") },
            text = {
                Column(
                    Modifier.verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text("Veggie Prep does not require an account and Vadlamudi Labs does not collect your pantry or meal data.")
                    Text("Pantry items, generated meals, imported models, and AI settings are stored in this app's private storage. Android cloud backup is disabled.")
                    Text("On-device meal generation does not send pantry data to a server.")
                    Text("If you choose a network AI, the app shows the destination and exact pantry preview before sending. Only item names, quantities, units, expiry dates, and your meal request are sent. Storage locations, purchase dates, and inventory history remain on this phone.")
                    Text("Any network AI provider you configure processes the data under its own privacy terms. You can remove all local data by clearing the app's storage or uninstalling it.")
                }
            },
            confirmButton = {
                Button(onClick = { showPrivacy = false }) { Text("Done") }
            },
        )
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
private fun EmptyState(
    title: String,
    detail: String,
    button: String?,
    onClick: () -> Unit = {},
) {
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
        if (button != null) {
            Spacer(Modifier.height(18.dp))
            Button(onClick = onClick) { Text(button) }
        }
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

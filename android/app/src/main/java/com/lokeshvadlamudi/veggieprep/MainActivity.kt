package com.lokeshvadlamudi.veggieprep

import android.app.Activity
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.LocalActivity
import androidx.activity.result.IntentSenderRequest
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
import androidx.compose.material3.SnackbarResult
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
import com.lokeshvadlamudi.veggieprep.data.groupMatchingPantryItems
import com.lokeshvadlamudi.veggieprep.ai.MealPlanningPolicy
import com.google.mlkit.vision.documentscanner.GmsDocumentScannerOptions
import com.google.mlkit.vision.documentscanner.GmsDocumentScanning
import com.google.mlkit.vision.documentscanner.GmsDocumentScanningResult
import com.lokeshvadlamudi.veggieprep.receipt.ReceiptCandidate
import com.lokeshvadlamudi.veggieprep.receipt.ReceiptConfidence
import com.lokeshvadlamudi.veggieprep.receipt.ReceiptDraft
import com.lokeshvadlamudi.veggieprep.receipt.ReceiptParser
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
    val weekly: Boolean = false,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun VeggiePrepApp(viewModel: MainViewModel) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    var section by rememberSaveable { mutableStateOf(AppSection.PANTRY) }
    val snackbar = remember { SnackbarHostState() }
    val activity = LocalActivity.current
    val documentScanner = remember {
        GmsDocumentScanning.getClient(
            GmsDocumentScannerOptions.Builder()
                .setGalleryImportAllowed(true)
                .setPageLimit(2)
                .setResultFormats(GmsDocumentScannerOptions.RESULT_FORMAT_JPEG)
                .setScannerMode(GmsDocumentScannerOptions.SCANNER_MODE_BASE_WITH_FILTER)
                .build(),
        )
    }
    val receiptScannerLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartIntentSenderForResult(),
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            val pages = GmsDocumentScanningResult.fromActivityResultIntent(result.data)
                ?.pages
                .orEmpty()
                .map { it.imageUri }
            if (pages.isEmpty()) viewModel.reportError("No receipt image was returned.")
            else viewModel.processReceipt(pages)
        }
    }
    val receiptPhotoPicker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        uri?.let { viewModel.processReceipt(listOf(it)) }
    }

    fun startReceiptScan() {
        val hostActivity = activity ?: run {
            viewModel.reportError("Could not open the receipt scanner from this screen.")
            return
        }
        documentScanner.getStartScanIntent(hostActivity)
            .addOnSuccessListener { sender ->
                receiptScannerLauncher.launch(IntentSenderRequest.Builder(sender).build())
            }
            .addOnFailureListener { viewModel.reportError("Could not open the receipt scanner. ${it.message.orEmpty()}") }
    }

    LaunchedEffect(state.error, state.status, state.busy, state.lastReceiptImportId) {
        val message = state.error ?: state.status.takeIf { !state.busy && it.isNotBlank() }
        if (message != null) {
            val importId = state.lastReceiptImportId
            val result = snackbar.showSnackbar(
                message = message,
                actionLabel = if (importId != null) "Undo" else null,
                withDismissAction = importId != null,
            )
            if (result == SnackbarResult.ActionPerformed && importId != null) {
                viewModel.undoReceiptImport(importId)
            }
            viewModel.clearMessage()
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("Veggie Prep", fontWeight = FontWeight.Bold)
                        Text(if (state.receiptDraft != null) "Review receipt" else section.label, style = MaterialTheme.typography.labelMedium)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Cream),
            )
        },
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            if (state.receiptDraft == null) NavigationBar(containerColor = Color.White) {
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
            val receipt = state.receiptDraft
            if (receipt != null) {
                ReceiptReviewScreen(
                    draft = receipt,
                    onUpdate = viewModel::updateReceiptCandidate,
                    onImport = viewModel::importReceipt,
                    onCancel = viewModel::dismissReceipt,
                )
            } else when (section) {
                AppSection.PANTRY -> PantryScreen(
                    pantry = state.pantry,
                    onAdd = viewModel::addItem,
                    onUse = viewModel::useItems,
                    onUpdateDetails = viewModel::updateItemDetails,
                    onScanReceipt = ::startReceiptScan,
                    onChooseReceiptPhoto = { receiptPhotoPicker.launch("image/*") },
                )
                AppSection.SNACKS -> PantryScreen(
                    pantry = state.pantry.filter { IndianIngredientCatalog.isSnack(it.name, it.category) },
                    onAdd = viewModel::addItem,
                    onUse = viewModel::useItems,
                    onUpdateDetails = viewModel::updateItemDetails,
                    heading = "Available snacks",
                    emptyTitle = "No snacks yet",
                    emptyDetail = "Add chips, biscuits, namkeen, sweets, bakery items, or any custom snack.",
                    emptyButton = "Add a snack",
                    snacksOnly = true,
                )
                AppSection.MEALS -> MealsScreen(
                    state = state,
                    onGenerate = viewModel::generateMeal,
                    onGenerateWeek = viewModel::generateWeeklyPlan,
                    onCook = viewModel::cookMeal,
                    onAddMissing = {
                        viewModel.addMissingToShopping(it)
                        section = AppSection.SHOPPING
                    },
                    onAddWeeklyMissing = {
                        viewModel.addWeeklyMissingToShopping()
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
    onUse: (List<PantryItem>, String, Boolean) -> Unit,
    onUpdateDetails: (List<PantryItem>, String, String, String) -> Unit,
    onScanReceipt: (() -> Unit)? = null,
    onChooseReceiptPhoto: (() -> Unit)? = null,
    heading: String = "Use soon",
    emptyTitle: String = "Your pantry lives on this phone",
    emptyDetail: String = "Add vegetables and staples. No account or server is needed.",
    emptyButton: String = "Add first item",
    snacksOnly: Boolean = false,
) {
    var showAdd by rememberSaveable { mutableStateOf(false) }
    var showAddChoice by rememberSaveable { mutableStateOf(false) }
    var search by rememberSaveable { mutableStateOf("") }
    var actionItems by remember { mutableStateOf<List<PantryItem>?>(null) }
    var editItems by remember { mutableStateOf<List<PantryItem>?>(null) }
    var discard by remember { mutableStateOf(false) }
    val groupedPantry = remember(pantry) { groupMatchingPantryItems(pantry) }
    val visibleGroups = remember(groupedPantry, search) {
        groupedPantry.filter { it.summary.matchesPantrySearch(search) }
    }

    Box(Modifier.fillMaxSize()) {
        if (pantry.isEmpty()) {
            EmptyState(
                title = emptyTitle,
                detail = emptyDetail,
                button = emptyButton,
                onClick = { if (onScanReceipt == null) showAdd = true else showAddChoice = true },
            )
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp, 12.dp, 16.dp, 96.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                item { Text(heading, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold) }
                item {
                    OutlinedTextField(
                        value = search,
                        onValueChange = { search = it },
                        label = { Text(if (snacksOnly) "Search snacks" else "Search pantry") },
                        supportingText = { Text("Names, categories, storage, and regional aliases") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                    )
                }
                if (visibleGroups.isEmpty()) {
                    item {
                        Text(
                            "No items match “${search.trim()}”.",
                            color = Muted,
                            modifier = Modifier.padding(vertical = 24.dp),
                        )
                    }
                }
                items(visibleGroups, key = { it.summary.id }) { group ->
                    PantryCard(
                        item = group.summary,
                        matchingEntries = group.lots.size,
                        onUse = { actionItems = group.lots; discard = false },
                        onEdit = { editItems = group.lots },
                        onDiscard = { actionItems = group.lots; discard = true },
                    )
                }
            }
        }
        FloatingActionButton(
            onClick = { if (onScanReceipt == null) showAdd = true else showAddChoice = true },
            modifier = Modifier.align(Alignment.BottomEnd).padding(20.dp),
            containerColor = Leaf,
            contentColor = Color.White,
        ) { Text("+", style = MaterialTheme.typography.headlineMedium) }
    }

    if (showAddChoice && onScanReceipt != null) {
        AlertDialog(
            onDismissRequest = { showAddChoice = false },
            title = { Text("Add groceries") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Button(
                        onClick = { showAddChoice = false; onScanReceipt() },
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text("Scan a receipt") }
                    if (onChooseReceiptPhoto != null) {
                        OutlinedButton(
                            onClick = { showAddChoice = false; onChooseReceiptPhoto() },
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text("Choose a receipt photo") }
                    }
                    OutlinedButton(
                        onClick = { showAddChoice = false; showAdd = true },
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text("Search foods or add manually") }
                    Text(
                        "Receipt text is read on this phone. You choose every item before it is saved.",
                        color = Muted,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            },
            confirmButton = {},
            dismissButton = { TextButton(onClick = { showAddChoice = false }) { Text("Cancel") } },
        )
    }

    if (showAdd) QuickAddDialog(snacksOnly = snacksOnly, onDismiss = { showAdd = false }) { name, quantity, unit, location, purchased, expires, category ->
        onAdd(name, quantity, unit, location, purchased, expires, category)
        showAdd = false
    }
    actionItems?.let { items ->
        QuantityDialog(
            item = groupMatchingPantryItems(items).single().summary,
            discard = discard,
            onDismiss = { actionItems = null },
            onConfirm = { quantity -> onUse(items, quantity, discard); actionItems = null },
        )
    }
    editItems?.let { items ->
        ItemDetailsDialog(
            item = groupMatchingPantryItems(items).single().summary,
            matchingEntries = items.size,
            onDismiss = { editItems = null },
            onConfirm = { name, expiry, icon -> onUpdateDetails(items, name, expiry, icon); editItems = null },
        )
    }
}

@Composable
private fun ReceiptReviewScreen(
    draft: ReceiptDraft,
    onUpdate: (ReceiptCandidate) -> Unit,
    onImport: () -> Unit,
    onCancel: () -> Unit,
) {
    var editing by remember { mutableStateOf<ReceiptCandidate?>(null) }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp, 12.dp, 16.dp, 32.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Card(colors = CardDefaults.cardColors(containerColor = PaleGreen), shape = RoundedCornerShape(18.dp)) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("${draft.candidates.size} grocery lines found", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                    Text("${draft.includedCount} selected • ${draft.needsReviewCount} need review", color = Muted)
                    Text("Purchased ${draft.purchasedOn} • ${draft.merchant}", color = Muted)
                    Text(
                        "Quantities and expiry dates marked Estimated are starting points. Check the package and freshness before importing.",
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
        }
        items(draft.candidates, key = { it.id }) { candidate ->
            Card(
                onClick = { editing = candidate },
                colors = CardDefaults.cardColors(containerColor = Color.White),
                shape = RoundedCornerShape(18.dp),
            ) {
                Row(
                    Modifier.fillMaxWidth().padding(12.dp),
                    verticalAlignment = Alignment.Top,
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Checkbox(
                        checked = candidate.included,
                        onCheckedChange = { onUpdate(candidate.copy(included = it)) },
                    )
                    Text(IndianIngredientCatalog.find(candidate.name)?.visual ?: "🧾", style = MaterialTheme.typography.headlineMedium)
                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                        Text(candidate.name, fontWeight = FontWeight.SemiBold)
                        Text(
                            "${formatMilli(candidate.quantityMilli)} ${candidate.unit}" +
                                if (candidate.quantityEstimated) " • Estimated" else "",
                            color = if (candidate.quantityEstimated) Muted else Leaf,
                        )
                        Text(
                            buildString {
                                append(candidate.location.replaceFirstChar(Char::uppercase))
                                if (candidate.expiresOn.isNotBlank()) {
                                    append(" • Expires ${candidate.expiresOn}")
                                    if (candidate.expiryEstimated) append(" (Estimated)")
                                }
                            },
                            color = Muted,
                            style = MaterialTheme.typography.bodySmall,
                        )
                        Text(
                            when (candidate.confidence) {
                                ReceiptConfidence.HIGH -> candidate.matchReason
                                ReceiptConfidence.REVIEW -> "Review: ${candidate.matchReason}"
                                ReceiptConfidence.LOW -> "Not selected: ${candidate.matchReason}"
                            },
                            color = if (candidate.confidence == ReceiptConfidence.HIGH) Leaf else Danger,
                            style = MaterialTheme.typography.bodySmall,
                        )
                        Text("Receipt: ${candidate.rawLabel}", color = Muted, style = MaterialTheme.typography.labelSmall)
                    }
                }
            }
        }
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedButton(onClick = onCancel, modifier = Modifier.weight(1f)) { Text("Cancel") }
                Button(
                    onClick = onImport,
                    enabled = draft.includedCount > 0,
                    modifier = Modifier.weight(1f),
                ) { Text("Add ${draft.includedCount} items") }
            }
        }
    }

    editing?.let { candidate ->
        ReceiptCandidateEditDialog(
            candidate = candidate,
            onDismiss = { editing = null },
            onSave = { revised -> onUpdate(revised); editing = null },
        )
    }
}

@Composable
private fun ReceiptCandidateEditDialog(
    candidate: ReceiptCandidate,
    onDismiss: () -> Unit,
    onSave: (ReceiptCandidate) -> Unit,
) {
    var name by rememberSaveable(candidate.id) { mutableStateOf(candidate.name) }
    var quantity by rememberSaveable(candidate.id) { mutableStateOf(formatMilli(candidate.quantityMilli)) }
    var unit by rememberSaveable(candidate.id) { mutableStateOf(candidate.unit) }
    var location by rememberSaveable(candidate.id) { mutableStateOf(candidate.location) }
    var expires by rememberSaveable(candidate.id) { mutableStateOf(candidate.expiresOn) }
    var included by rememberSaveable(candidate.id) { mutableStateOf(candidate.included) }
    var validationError by remember(candidate.id) { mutableStateOf<String?>(null) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Review receipt item") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Receipt: ${candidate.rawLabel}", color = Muted, style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(name, { name = it }, label = { Text("Food") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                OutlinedTextField(
                    quantity,
                    { quantity = it },
                    label = { Text("Quantity") },
                    modifier = Modifier.fillMaxWidth(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    singleLine = true,
                )
                Text("Unit", style = MaterialTheme.typography.labelLarge)
                ChoiceRow(FoodUnitOptions, unit) { unit = it }
                Text("Stored in", style = MaterialTheme.typography.labelLarge)
                ChoiceRow(listOf("fridge", "pantry", "freezer"), location) { location = it }
                OutlinedTextField(
                    expires,
                    { expires = it },
                    label = { Text("Expiry date (YYYY-MM-DD, optional)") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                )
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(checked = included, onCheckedChange = { included = it })
                    Text("Add this item to pantry")
                }
                validationError?.let { Text(it, color = Danger) }
            }
        },
        confirmButton = {
            Button(onClick = {
                runCatching {
                    ReceiptParser.revise(candidate, name, quantity, unit, location, expires, included)
                }.onSuccess(onSave).onFailure {
                    validationError = it.message ?: "Check this item and try again."
                }
            }) { Text("Save") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun PantryCard(
    item: PantryItem,
    matchingEntries: Int,
    onUse: () -> Unit,
    onEdit: () -> Unit,
    onDiscard: () -> Unit,
) {
    Card(colors = CardDefaults.cardColors(containerColor = Color.White), shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(item.icon ?: IndianIngredientCatalog.find(item.name)?.visual ?: "🧺", style = MaterialTheme.typography.headlineMedium)
                    Text(item.name, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
                }
                Text("${item.quantityText} ${item.unit}", color = Leaf, fontWeight = FontWeight.Bold)
            }
            Text(buildString {
                append(item.location.replaceFirstChar(Char::uppercase))
                item.expiresOn?.let {
                    append("  •  Expires $it")
                    if (item.expiryEstimated) append(" (Estimated)")
                }
                if (item.quantityEstimated) append("  •  Quantity estimated")
                if (matchingEntries > 1) append("  •  $matchingEntries matching entries combined")
            }, color = Muted)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onUse) { Text("Use") }
                TextButton(onClick = onEdit) { Text("Edit") }
                TextButton(onClick = onDiscard) { Text("Discard", color = Danger) }
            }
        }
    }
}

private fun PantryItem.matchesPantrySearch(query: String): Boolean {
    val normalized = query.trim().lowercase()
    if (normalized.isEmpty()) return true
    val catalog = IndianIngredientCatalog.find(name)
    return listOf(name, category, location, unit, catalog?.name.orEmpty())
        .plus(catalog?.aliases.orEmpty())
        .any { normalized in it.lowercase() }
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
                    ChoiceRow(FoodUnitOptions, unit) { unit = it }
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
private fun ItemDetailsDialog(
    item: PantryItem,
    matchingEntries: Int,
    onDismiss: () -> Unit,
    onConfirm: (String, String, String) -> Unit,
) {
    var name by rememberSaveable(item.id) { mutableStateOf(item.name) }
    var expires by rememberSaveable(item.id) { mutableStateOf(item.expiresOn.orEmpty()) }
    var icon by rememberSaveable(item.id) { mutableStateOf(item.icon.orEmpty()) }
    val defaultIcon = IndianIngredientCatalog.find(item.name)?.visual ?: "🧺"
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Edit ${item.name}") },
        text = {
            Column(
                Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it.take(200) },
                    label = { Text("Item name") },
                    supportingText = {
                        if (matchingEntries > 1) Text("This renames all $matchingEntries matching entries in this card.")
                    },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                )
                Text("Icon", style = MaterialTheme.typography.labelLarge)
                Text("Current: ${icon.ifBlank { defaultIcon }}", style = MaterialTheme.typography.headlineMedium)
                ChoiceRow(ItemIconOptions, icon) { icon = it }
                OutlinedTextField(
                    value = icon,
                    onValueChange = { icon = it.take(16) },
                    label = { Text("Custom emoji or short icon") },
                    supportingText = { Text("Paste an emoji, or leave blank to use $defaultIcon.") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                )
                if (icon.isNotBlank()) {
                    TextButton(onClick = { icon = "" }) { Text("Reset to default $defaultIcon") }
                }
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
        confirmButton = {
            Button(onClick = { onConfirm(name, expires, icon) }, enabled = name.isNotBlank()) { Text("Save") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun MealsScreen(
    state: AppUiState,
    onGenerate: (Int, Int, String, Boolean, Boolean) -> Unit,
    onGenerateWeek: (Int, Int, String, Boolean, Boolean) -> Unit,
    onCook: (MealProposal) -> Unit,
    onAddMissing: (MealProposal) -> Unit,
    onAddWeeklyMissing: () -> Unit,
    openSettings: () -> Unit,
) {
    var servingsText by rememberSaveable { mutableStateOf("2") }
    var minutesText by rememberSaveable { mutableStateOf("45") }
    var preference by rememberSaveable { mutableStateOf("") }
    var pendingRequest by remember { mutableStateOf<PendingMealRequest?>(null) }
    var rememberNetworkDisclosure by rememberSaveable { mutableStateOf(false) }

    fun requestMeal(weekly: Boolean = false, forceDisclosure: Boolean = false) {
        val request = PendingMealRequest(
            servings = servingsText.toIntOrNull()?.coerceIn(1, 20) ?: 2,
            maxMinutes = minutesText.toIntOrNull()?.coerceIn(5, 360) ?: 45,
            preference = preference,
            weekly = weekly,
        )
        if (state.pantry.isEmpty()) {
            if (weekly) onGenerateWeek(request.servings, request.maxMinutes, request.preference, false, false)
            else onGenerate(request.servings, request.maxMinutes, request.preference, false, false)
        } else if (
            state.settings.provider == AiProviderType.REMOTE_OPENAI &&
            (forceDisclosure || !state.networkDisclosureRemembered)
        ) {
            rememberNetworkDisclosure = state.networkDisclosureRemembered
            pendingRequest = request
        } else {
            if (weekly) onGenerateWeek(request.servings, request.maxMinutes, request.preference, false, false)
            else onGenerate(request.servings, request.maxMinutes, request.preference, false, false)
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
                        OutlinedButton(
                            onClick = { requestMeal(weekly = true) },
                            enabled = !state.busy,
                        ) { Text("Plan next week") }
                    }
                    TextButton(onClick = openSettings) { Text("Change AI") }
                    if (state.settings.provider == AiProviderType.REMOTE_OPENAI) {
                        TextButton(onClick = { requestMeal(forceDisclosure = true) }) {
                            Text("Review what will be shared")
                        }
                    }
                }
            }
        }
        val weeklyPlan = state.weeklyPlan
        val weeklyMeals = state.meals.filter { it.planId == weeklyPlan?.id }.sortedBy { it.plannedFor }
        if (weeklyPlan != null && weeklyMeals.isNotEmpty()) {
            item {
                Card(colors = CardDefaults.cardColors(containerColor = PaleGreen), shape = RoundedCornerShape(18.dp)) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("Week of ${weeklyPlan.weekStart}", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                        Text("${weeklyMeals.size} meals • expiry-aware pantry reservations", color = Muted)
                        if (weeklyMeals.any { it.missingIngredients.isNotEmpty() }) {
                            OutlinedButton(onClick = onAddWeeklyMissing) { Text("Add all missing items to shopping") }
                        }
                    }
                }
            }
            items(weeklyMeals, key = { "weekly-${it.id}" }) { meal ->
                MealCard(meal, onCook = { onCook(meal) }, onAddMissing = { onAddMissing(meal) })
            }
        }
        val savedMeals = state.meals.filter { it.planId == null }
        if (savedMeals.isEmpty() && weeklyMeals.isEmpty()) {
            item { Text("Generated meals will be saved here on this phone.", color = Muted, modifier = Modifier.padding(8.dp)) }
        } else if (savedMeals.isNotEmpty()) {
            item { Text("Saved meals", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold) }
            items(savedMeals, key = { it.id }) { meal ->
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
                if (request.weekly) {
                    onGenerateWeek(
                        request.servings,
                        request.maxMinutes,
                        request.preference,
                        true,
                        rememberNetworkDisclosure,
                    )
                } else {
                    onGenerate(
                        request.servings,
                        request.maxMinutes,
                        request.preference,
                        true,
                        rememberNetworkDisclosure,
                    )
                }
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
                    "${if (request.weekly) "Five-meal weekday plan" else "Meal request"}: ${request.servings} servings, up to ${request.maxMinutes} minutes per meal. Preference: ${request.preference.ifBlank { "none" }}.",
                )
                Text(
                    "Expired items, storage locations, purchase dates, and inventory history are not sent. If configured, the API key is sent separately as an authorization header and is never included in the meal prompt.",
                    color = Muted,
                    style = MaterialTheme.typography.bodySmall,
                )
                if (request.weekly) {
                    Text(
                        "The remaining pantry snapshot is updated and sent once for each of the five meals.",
                        color = Muted,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(
                        checked = rememberChoice,
                        onCheckedChange = onRememberChoiceChange,
                    )
                    Text("Don't ask again for this API address")
                }
            }
        },
        confirmButton = { Button(onClick = onConfirm) { Text(if (request.weekly) "Send and plan week" else "Send and suggest") } },
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
            meal.plannedFor?.let { Text("Planned for $it", color = Leaf, fontWeight = FontWeight.SemiBold) }
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
                    Text("Receipt photos are processed on the device through Android and ML Kit. Veggie Prep does not keep the original photo; only the grocery lines you approve are saved locally. Google Play services may collect limited operational diagnostics under Google's terms.")
                    Text("On-device meal generation does not send pantry data to a server.")
                    Text("If you choose a network AI, the app shows the destination and exact pantry preview before sending. Only item names, quantities, units, expiry dates, and your meal request are sent. A five-meal plan makes up to five requests with the remaining pantry. Storage locations, purchase dates, and inventory history remain on this phone.")
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
private val FoodUnitOptions = listOf("count", "each", "oz", "lb", "g", "kg", "ml", "l")
private val ItemIconOptions = listOf(
    "🥬", "🍅", "🥔", "🥕", "🥑", "🍎", "🍌", "🍞", "🫓", "🥚", "🥛", "🧀",
    "🍚", "🍜", "🫘", "🥜", "🍿", "🍪", "🍫", "🧃", "🧊", "🧺",
)
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

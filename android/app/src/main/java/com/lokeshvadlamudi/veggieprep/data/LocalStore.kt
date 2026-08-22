package com.lokeshvadlamudi.veggieprep.data

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.lokeshvadlamudi.veggieprep.receipt.ReceiptDraft
import com.lokeshvadlamudi.veggieprep.receipt.ReceiptImportResult
import java.util.UUID

class LocalStore(
    context: Context,
    databaseName: String = "veggie_prep.db",
) : SQLiteOpenHelper(context, databaseName, null, 6) {
    private val gson = Gson()

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE stock_lots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                purchase_quantity_milli INTEGER NOT NULL CHECK(purchase_quantity_milli > 0),
                unit TEXT NOT NULL,
                location TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'Other',
                purchased_on TEXT,
                expires_on TEXT,
                expiry_estimated INTEGER NOT NULL DEFAULT 0,
                quantity_estimated INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'manual',
                source_ref INTEGER,
                icon TEXT,
                created_at INTEGER NOT NULL
            )
            """.trimIndent(),
        )
        db.execSQL(
            """
            CREATE TABLE inventory_events (
                id TEXT PRIMARY KEY,
                lot_id INTEGER NOT NULL REFERENCES stock_lots(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                quantity_milli INTEGER NOT NULL,
                note TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """.trimIndent(),
        )
        db.execSQL(
            """
            CREATE TABLE meals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                servings INTEGER NOT NULL,
                time_minutes INTEGER NOT NULL,
                steps_json TEXT NOT NULL,
                substitutions_json TEXT NOT NULL,
                safety_note TEXT NOT NULL,
                rationale TEXT NOT NULL,
                ingredients_json TEXT NOT NULL,
                provider TEXT NOT NULL,
                allocations_json TEXT NOT NULL DEFAULT '[]',
                missing_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'suggested',
                cooked_at INTEGER,
                plan_id INTEGER,
                planned_for TEXT,
                created_at INTEGER NOT NULL
            )
            """.trimIndent(),
        )
        createShoppingTable(db)
        createReceiptTables(db)
        createWeeklyPlanTable(db)
        db.execSQL("CREATE INDEX inventory_events_lot ON inventory_events(lot_id, created_at)")
        db.execSQL("CREATE INDEX stock_lots_expiry ON stock_lots(expires_on)")
    }

    override fun onConfigure(db: SQLiteDatabase) {
        super.onConfigure(db)
        db.setForeignKeyConstraintsEnabled(true)
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        if (oldVersion < 2) {
            db.execSQL("ALTER TABLE meals ADD COLUMN allocations_json TEXT NOT NULL DEFAULT '[]'")
            db.execSQL("ALTER TABLE meals ADD COLUMN missing_json TEXT NOT NULL DEFAULT '[]'")
            db.execSQL("ALTER TABLE meals ADD COLUMN status TEXT NOT NULL DEFAULT 'suggested'")
            db.execSQL("ALTER TABLE meals ADD COLUMN cooked_at INTEGER")
            createShoppingTable(db)
        }
        if (oldVersion < 3) {
            db.execSQL("ALTER TABLE stock_lots ADD COLUMN category TEXT NOT NULL DEFAULT 'Other'")
        }
        if (oldVersion < 4) {
            db.execSQL("ALTER TABLE stock_lots ADD COLUMN expiry_estimated INTEGER NOT NULL DEFAULT 0")
            db.execSQL("ALTER TABLE stock_lots ADD COLUMN quantity_estimated INTEGER NOT NULL DEFAULT 0")
            db.execSQL("ALTER TABLE stock_lots ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'")
            db.execSQL("ALTER TABLE stock_lots ADD COLUMN source_ref INTEGER")
            createReceiptTables(db)
        }
        if (oldVersion < 5) {
            db.execSQL("ALTER TABLE meals ADD COLUMN plan_id INTEGER")
            db.execSQL("ALTER TABLE meals ADD COLUMN planned_for TEXT")
            createWeeklyPlanTable(db)
        }
        if (oldVersion < 6) {
            db.execSQL("ALTER TABLE stock_lots ADD COLUMN icon TEXT")
        }
    }

    fun addLot(
        name: String,
        quantityMilli: Long,
        unit: String,
        location: String,
        purchasedOn: String?,
        expiresOn: String?,
        category: String = "Other",
    ): Long = writableDatabase.inTransaction {
        val now = System.currentTimeMillis()
        insertLot(
            db = this,
            name = name,
            quantityMilli = quantityMilli,
            unit = unit,
            location = location,
            purchasedOn = purchasedOn,
            expiresOn = expiresOn,
            category = category,
            expiryEstimated = false,
            quantityEstimated = false,
            source = "manual",
            sourceRef = null,
            now = now,
        )
    }

    fun importReceipt(draft: ReceiptDraft): ReceiptImportResult = writableDatabase.inTransaction {
        require(draft.candidates.any { it.included }) { "Select at least one grocery to add." }
        val duplicate = rawQuery(
            "SELECT id FROM receipt_imports WHERE fingerprint = ? LIMIT 1",
            arrayOf(draft.fingerprint),
        ).use { it.moveToFirst() }
        require(!duplicate) { "This receipt was already imported." }
        val now = System.currentTimeMillis()
        val importId = insertOrThrow(
            "receipt_imports",
            null,
            ContentValues().apply {
                put("fingerprint", draft.fingerprint)
                put("merchant", draft.merchant.take(120))
                put("purchased_on", draft.purchasedOn)
                put("created_at", now)
            },
        )
        var added = 0
        draft.candidates.forEach { candidate ->
            var lotId: Long? = null
            if (candidate.included) {
                require(candidate.name.isNotBlank()) { "Every selected grocery needs a name." }
                require(candidate.quantityMilli > 0) { "Every selected grocery needs a positive quantity." }
                lotId = insertLot(
                    db = this,
                    name = candidate.name,
                    quantityMilli = candidate.quantityMilli,
                    unit = candidate.unit,
                    location = candidate.location,
                    purchasedOn = draft.purchasedOn,
                    expiresOn = candidate.expiresOn,
                    category = candidate.category,
                    expiryEstimated = candidate.expiryEstimated,
                    quantityEstimated = candidate.quantityEstimated,
                    source = "receipt",
                    sourceRef = importId,
                    now = now,
                    note = "Imported from ${draft.merchant}",
                )
                added++
            }
            insertOrThrow(
                "receipt_import_lines",
                null,
                ContentValues().apply {
                    put("import_id", importId)
                    put("raw_label", candidate.rawLabel.take(160))
                    put("normalized_name", candidate.name.take(120))
                    put("included", if (candidate.included) 1 else 0)
                    lotId?.let { put("lot_id", it) }
                },
            )
        }
        ReceiptImportResult(importId, added)
    }

    fun undoReceiptImport(importId: Long) {
        writableDatabase.inTransaction {
            val lotIds = rawQuery(
                "SELECT id, purchase_quantity_milli FROM stock_lots WHERE source = 'receipt' AND source_ref = ?",
                arrayOf(importId.toString()),
            ).use { cursor ->
                buildList {
                    while (cursor.moveToNext()) add(cursor.getLong(0) to cursor.getLong(1))
                }
            }
            require(lotIds.isNotEmpty()) { "That receipt import is no longer available to undo." }
            lotIds.forEach { (lotId, originalQuantity) ->
                require(balanceFor(this, lotId) == originalQuantity) {
                    "Some imported groceries were already used. Undo them individually instead."
                }
                val eventCount = rawQuery(
                    "SELECT COUNT(*) FROM inventory_events WHERE lot_id = ?",
                    arrayOf(lotId.toString()),
                ).use { cursor -> cursor.moveToFirst(); cursor.getInt(0) }
                require(eventCount == 1) { "Some imported groceries were already changed." }
            }
            lotIds.forEach { (lotId, _) -> delete("stock_lots", "id = ?", arrayOf(lotId.toString())) }
            delete("receipt_imports", "id = ?", arrayOf(importId.toString()))
        }
    }

    fun changeQuantity(lotId: Long, amountMilli: Long, eventType: String, note: String = "") {
        require(eventType in setOf("CONSUME", "DISCARD", "ADJUST"))
        require(amountMilli != 0L)
        writableDatabase.inTransaction {
            val current = balanceFor(this, lotId)
            val signed = when (eventType) {
                "CONSUME", "DISCARD" -> -kotlin.math.abs(amountMilli)
                else -> amountMilli
            }
            require(current + signed >= 0) { "Quantity cannot go below zero." }
            insertEvent(this, lotId, eventType, signed, note, System.currentTimeMillis())
        }
    }

    fun changeQuantityAcrossLots(lotIds: List<Long>, amountMilli: Long, eventType: String, note: String = "") {
        require(lotIds.isNotEmpty())
        require(eventType in setOf("CONSUME", "DISCARD"))
        require(amountMilli > 0L)
        writableDatabase.inTransaction {
            var remaining = amountMilli
            lotIds.distinct().forEach { lotId ->
                if (remaining == 0L) return@forEach
                val available = balanceFor(this, lotId)
                val used = minOf(available, remaining)
                if (used > 0L) {
                    insertEvent(this, lotId, eventType, -used, note, System.currentTimeMillis())
                    remaining -= used
                }
            }
            require(remaining == 0L) { "Quantity cannot go below zero." }
        }
    }

    fun updateLotExpiry(lotId: Long, expiresOn: String?) {
        val updated = writableDatabase.update(
            "stock_lots",
            ContentValues().apply {
                val normalized = expiresOn?.trim().orEmpty()
                if (normalized.isEmpty()) putNull("expires_on") else put("expires_on", normalized)
                put("expiry_estimated", 0)
            },
            "id = ?",
            arrayOf(lotId.toString()),
        )
        require(updated == 1) { "That pantry item is no longer available." }
    }

    fun updateLotDetails(lotId: Long, name: String, expiresOn: String?, icon: String?) {
        updateLotDetails(listOf(lotId), name, expiresOn, icon)
    }

    fun updateLotDetails(lotIds: List<Long>, name: String, expiresOn: String?, icon: String?) {
        require(lotIds.isNotEmpty())
        val normalizedName = name.trim()
        require(normalizedName.isNotEmpty() && normalizedName.length <= 200) { "Enter an item name up to 200 characters." }
        val normalizedIcon = icon?.trim().orEmpty()
        require(normalizedIcon.length <= 16) { "Choose one short icon." }
        writableDatabase.inTransaction {
            lotIds.distinct().forEach { lotId ->
                val updated = update(
                    "stock_lots",
                    ContentValues().apply {
                        put("name", normalizedName)
                        val normalizedExpiry = expiresOn?.trim().orEmpty()
                        if (normalizedExpiry.isEmpty()) putNull("expires_on") else put("expires_on", normalizedExpiry)
                        put("expiry_estimated", 0)
                        if (normalizedIcon.isEmpty()) putNull("icon") else put("icon", normalizedIcon)
                    },
                    "id = ?",
                    arrayOf(lotId.toString()),
                )
                require(updated == 1) { "That pantry item is no longer available." }
            }
        }
    }

    fun listPantry(): List<PantryItem> {
        val sql = """
            SELECT l.id, l.name, l.unit, l.location, l.category, l.purchased_on, l.expires_on,
                   l.expiry_estimated, l.quantity_estimated, l.source, l.source_ref,
                   l.icon, COALESCE(SUM(e.quantity_milli), 0) AS balance
            FROM stock_lots l
            LEFT JOIN inventory_events e ON e.lot_id = l.id
            GROUP BY l.id
            HAVING balance > 0
            ORDER BY CASE WHEN l.expires_on IS NULL THEN 1 ELSE 0 END,
                     l.expires_on, l.created_at
        """.trimIndent()
        return readableDatabase.rawQuery(sql, null).use { cursor ->
            buildList {
                while (cursor.moveToNext()) {
                    add(
                        PantryItem(
                            id = cursor.getLong(0),
                            name = cursor.getString(1),
                            unit = cursor.getString(2),
                            location = cursor.getString(3),
                            category = cursor.getString(4),
                            purchasedOn = cursor.getStringOrNull(5),
                            expiresOn = cursor.getStringOrNull(6),
                            expiryEstimated = cursor.getInt(7) != 0,
                            quantityEstimated = cursor.getInt(8) != 0,
                            source = cursor.getString(9),
                            sourceRef = cursor.getLongOrNull(10),
                            icon = cursor.getStringOrNull(11),
                            quantityMilli = cursor.getLong(12),
                        ),
                    )
                }
            }
        }
    }

    fun saveMeal(meal: MealProposal): Long = insertMeal(writableDatabase, meal)

    fun saveWeeklyPlan(plan: WeeklyPlan, meals: List<MealProposal>): Long = writableDatabase.inTransaction {
        require(meals.isNotEmpty()) { "A weekly plan needs at least one meal." }
        val planId = insertOrThrow(
            "weekly_plans",
            null,
            ContentValues().apply {
                put("week_start", plan.weekStart)
                put("servings", plan.servings)
                put("max_minutes", plan.maxMinutes)
                put("preference", plan.preference.take(500))
                put("provider", plan.provider)
                put("created_at", plan.createdAt)
            },
        )
        meals.forEachIndexed { index, meal ->
            insertMeal(
                this,
                meal.copy(
                    planId = planId,
                    plannedFor = meal.plannedFor ?: java.time.LocalDate.parse(plan.weekStart).plusDays(index.toLong()).toString(),
                ),
            )
        }
        planId
    }

    fun latestWeeklyPlan(): WeeklyPlan? = readableDatabase.query(
        "weekly_plans",
        null,
        null,
        null,
        null,
        null,
        "created_at DESC",
        "1",
    ).use { cursor ->
        if (!cursor.moveToFirst()) return@use null
        WeeklyPlan(
            id = cursor.getLong(cursor.getColumnIndexOrThrow("id")),
            weekStart = cursor.getString(cursor.getColumnIndexOrThrow("week_start")),
            servings = cursor.getInt(cursor.getColumnIndexOrThrow("servings")),
            maxMinutes = cursor.getInt(cursor.getColumnIndexOrThrow("max_minutes")),
            preference = cursor.getString(cursor.getColumnIndexOrThrow("preference")),
            provider = cursor.getString(cursor.getColumnIndexOrThrow("provider")),
            createdAt = cursor.getLong(cursor.getColumnIndexOrThrow("created_at")),
        )
    }

    private fun insertMeal(db: SQLiteDatabase, meal: MealProposal): Long = db.insertOrThrow(
        "meals",
        null,
        ContentValues().apply {
            put("title", meal.title)
            put("servings", meal.servings)
            put("time_minutes", meal.timeMinutes)
            put("steps_json", gson.toJson(meal.steps))
            put("substitutions_json", gson.toJson(meal.substitutions))
            put("safety_note", meal.safetyNote)
            put("rationale", meal.rationale)
            put("ingredients_json", gson.toJson(meal.ingredients))
            put("provider", meal.provider)
            put("allocations_json", gson.toJson(meal.allocations))
            put("missing_json", gson.toJson(meal.missingIngredients))
            put("status", meal.status.name.lowercase())
            meal.cookedAt?.let { put("cooked_at", it) }
            meal.planId?.let { put("plan_id", it) }
            meal.plannedFor?.let { put("planned_for", it) }
            put("created_at", meal.createdAt)
        },
    )

    fun listMeals(): List<MealProposal> = readableDatabase.query(
        "meals",
        null,
        null,
        null,
        null,
        null,
        "created_at DESC",
    ).use { cursor ->
        val stringListType = object : TypeToken<List<String>>() {}.type
        val ingredientType = object : TypeToken<List<MealIngredient>>() {}.type
        val allocationType = object : TypeToken<List<MealAllocation>>() {}.type
        buildList {
            while (cursor.moveToNext()) {
                add(
                    MealProposal(
                        id = cursor.getLong(cursor.getColumnIndexOrThrow("id")),
                        title = cursor.getString(cursor.getColumnIndexOrThrow("title")),
                        servings = cursor.getInt(cursor.getColumnIndexOrThrow("servings")),
                        timeMinutes = cursor.getInt(cursor.getColumnIndexOrThrow("time_minutes")),
                        steps = gson.fromJson(cursor.getString(cursor.getColumnIndexOrThrow("steps_json")), stringListType),
                        substitutions = gson.fromJson(cursor.getString(cursor.getColumnIndexOrThrow("substitutions_json")), stringListType),
                        safetyNote = cursor.getString(cursor.getColumnIndexOrThrow("safety_note")),
                        rationale = cursor.getString(cursor.getColumnIndexOrThrow("rationale")),
                        ingredients = gson.fromJson(cursor.getString(cursor.getColumnIndexOrThrow("ingredients_json")), ingredientType),
                        provider = cursor.getString(cursor.getColumnIndexOrThrow("provider")),
                        allocations = gson.fromJson(cursor.getString(cursor.getColumnIndexOrThrow("allocations_json")), allocationType),
                        missingIngredients = gson.fromJson(cursor.getString(cursor.getColumnIndexOrThrow("missing_json")), ingredientType),
                        status = MealStatus.valueOf(cursor.getString(cursor.getColumnIndexOrThrow("status")).uppercase()),
                        cookedAt = cursor.getLongOrNull(cursor.getColumnIndexOrThrow("cooked_at")),
                        createdAt = cursor.getLong(cursor.getColumnIndexOrThrow("created_at")),
                        planId = cursor.getLongOrNull(cursor.getColumnIndexOrThrow("plan_id")),
                        plannedFor = cursor.getStringOrNull(cursor.getColumnIndexOrThrow("planned_for")),
                    ),
                )
            }
        }
    }

    fun cookMeal(mealId: Long) {
        writableDatabase.inTransaction {
            val meal = rawQuery(
                "SELECT title, status, allocations_json FROM meals WHERE id = ?",
                arrayOf(mealId.toString()),
            ).use { cursor ->
                require(cursor.moveToFirst()) { "That meal is no longer available." }
                Triple(cursor.getString(0), cursor.getString(1), cursor.getString(2))
            }
            require(meal.second == "suggested") { "That meal was already cooked." }
            val allocationType = object : TypeToken<List<MealAllocation>>() {}.type
            val allocations: List<MealAllocation> = gson.fromJson(meal.third, allocationType)
            require(allocations.isNotEmpty()) { "This older suggestion has no pantry allocation to deduct." }
            val byLot = allocations.groupBy { it.lotId }.mapValues { (_, values) ->
                values.first() to values.sumOf { it.quantityMilli }
            }
            byLot.forEach { (lotId, value) ->
                require(balanceFor(this, lotId) >= value.second) {
                    "Pantry quantities changed. Generate a fresh meal before cooking."
                }
            }
            val now = System.currentTimeMillis()
            byLot.forEach { (lotId, value) ->
                insertEvent(this, lotId, "CONSUME", -value.second, "Cooked: ${meal.first}", now)
            }
            update(
                "meals",
                ContentValues().apply {
                    put("status", "cooked")
                    put("cooked_at", now)
                },
                "id = ?",
                arrayOf(mealId.toString()),
            )
        }
    }

    fun addShoppingItems(items: List<MealIngredient>) {
        writableDatabase.inTransaction {
            items.forEach { item ->
                val existing = rawQuery(
                    "SELECT id, quantity_milli FROM shopping_items WHERE lower(name) = lower(?) AND unit = ? AND checked = 0 ORDER BY id LIMIT 1",
                    arrayOf(item.name, item.unit),
                ).use { cursor ->
                    if (cursor.moveToFirst()) cursor.getLong(0) to cursor.getLong(1) else null
                }
                if (existing == null) {
                    insertOrThrow(
                        "shopping_items",
                        null,
                        ContentValues().apply {
                            put("name", item.name)
                            put("quantity_milli", item.quantityMilli)
                            put("unit", item.unit)
                            put("checked", 0)
                            put("created_at", System.currentTimeMillis())
                        },
                    )
                } else {
                    update(
                        "shopping_items",
                        ContentValues().apply { put("quantity_milli", Math.addExact(existing.second, item.quantityMilli)) },
                        "id = ?",
                        arrayOf(existing.first.toString()),
                    )
                }
            }
        }
    }

    fun listShopping(): List<ShoppingItem> = readableDatabase.query(
        "shopping_items",
        null,
        null,
        null,
        null,
        null,
        "checked ASC, created_at DESC",
    ).use { cursor ->
        buildList {
            while (cursor.moveToNext()) {
                add(
                    ShoppingItem(
                        id = cursor.getLong(cursor.getColumnIndexOrThrow("id")),
                        name = cursor.getString(cursor.getColumnIndexOrThrow("name")),
                        quantityMilli = cursor.getLong(cursor.getColumnIndexOrThrow("quantity_milli")),
                        unit = cursor.getString(cursor.getColumnIndexOrThrow("unit")),
                        checked = cursor.getInt(cursor.getColumnIndexOrThrow("checked")) != 0,
                    ),
                )
            }
        }
    }

    fun setShoppingChecked(itemId: Long, checked: Boolean) {
        writableDatabase.update(
            "shopping_items",
            ContentValues().apply { put("checked", if (checked) 1 else 0) },
            "id = ?",
            arrayOf(itemId.toString()),
        )
    }

    fun clearCheckedShopping() {
        writableDatabase.delete("shopping_items", "checked = 1", null)
    }

    private fun createShoppingTable(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE IF NOT EXISTS shopping_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                quantity_milli INTEGER NOT NULL CHECK(quantity_milli > 0),
                unit TEXT NOT NULL,
                checked INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL
            )
            """.trimIndent(),
        )
        db.execSQL("CREATE INDEX IF NOT EXISTS shopping_items_checked ON shopping_items(checked, created_at)")
    }

    private fun createReceiptTables(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE IF NOT EXISTS receipt_imports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL UNIQUE,
                merchant TEXT NOT NULL,
                purchased_on TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """.trimIndent(),
        )
        db.execSQL(
            """
            CREATE TABLE IF NOT EXISTS receipt_import_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                import_id INTEGER NOT NULL REFERENCES receipt_imports(id) ON DELETE CASCADE,
                raw_label TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                included INTEGER NOT NULL,
                lot_id INTEGER REFERENCES stock_lots(id) ON DELETE SET NULL
            )
            """.trimIndent(),
        )
        db.execSQL("CREATE INDEX IF NOT EXISTS receipt_lines_import ON receipt_import_lines(import_id)")
    }

    private fun createWeeklyPlanTable(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE IF NOT EXISTS weekly_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start TEXT NOT NULL,
                servings INTEGER NOT NULL,
                max_minutes INTEGER NOT NULL,
                preference TEXT NOT NULL,
                provider TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """.trimIndent(),
        )
        db.execSQL("CREATE INDEX IF NOT EXISTS meals_plan_day ON meals(plan_id, planned_for)")
    }

    private fun insertLot(
        db: SQLiteDatabase,
        name: String,
        quantityMilli: Long,
        unit: String,
        location: String,
        purchasedOn: String?,
        expiresOn: String?,
        category: String,
        expiryEstimated: Boolean,
        quantityEstimated: Boolean,
        source: String,
        sourceRef: Long?,
        now: Long,
        note: String = "Added",
    ): Long {
        val lotId = db.insertOrThrow(
            "stock_lots",
            null,
            ContentValues().apply {
                put("name", name.trim())
                put("purchase_quantity_milli", quantityMilli)
                put("unit", unit)
                put("location", location)
                put("category", category.ifBlank { "Other" })
                put("purchased_on", purchasedOn?.takeIf(String::isNotBlank))
                put("expires_on", expiresOn?.takeIf(String::isNotBlank))
                put("expiry_estimated", if (expiryEstimated) 1 else 0)
                put("quantity_estimated", if (quantityEstimated) 1 else 0)
                put("source", source)
                sourceRef?.let { put("source_ref", it) }
                put("created_at", now)
            },
        )
        insertEvent(db, lotId, "ADD", quantityMilli, note, now)
        return lotId
    }

    private fun insertEvent(
        db: SQLiteDatabase,
        lotId: Long,
        type: String,
        signedQuantityMilli: Long,
        note: String,
        now: Long,
    ) {
        db.insertOrThrow(
            "inventory_events",
            null,
            ContentValues().apply {
                put("id", UUID.randomUUID().toString())
                put("lot_id", lotId)
                put("event_type", type)
                put("quantity_milli", signedQuantityMilli)
                put("note", note.take(200))
                put("created_at", now)
            },
        )
    }

    private fun balanceFor(db: SQLiteDatabase, lotId: Long): Long = db.rawQuery(
        "SELECT COALESCE(SUM(quantity_milli), 0) FROM inventory_events WHERE lot_id = ?",
        arrayOf(lotId.toString()),
    ).use { cursor ->
        cursor.moveToFirst()
        cursor.getLong(0)
    }
}

private inline fun <T> SQLiteDatabase.inTransaction(block: SQLiteDatabase.() -> T): T {
    beginTransaction()
    try {
        val result = block()
        setTransactionSuccessful()
        return result
    } finally {
        endTransaction()
    }
}

private fun android.database.Cursor.getStringOrNull(index: Int): String? =
    if (isNull(index)) null else getString(index)

private fun android.database.Cursor.getLongOrNull(index: Int): Long? =
    if (isNull(index)) null else getLong(index)

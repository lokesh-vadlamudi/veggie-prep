package com.lokeshvadlamudi.veggieprep.data

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import java.util.UUID

class LocalStore(
    context: Context,
    databaseName: String = "veggie_prep.db",
) : SQLiteOpenHelper(context, databaseName, null, 2) {
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
                purchased_on TEXT,
                expires_on TEXT,
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
                created_at INTEGER NOT NULL
            )
            """.trimIndent(),
        )
        createShoppingTable(db)
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
    }

    fun addLot(
        name: String,
        quantityMilli: Long,
        unit: String,
        location: String,
        purchasedOn: String?,
        expiresOn: String?,
    ): Long = writableDatabase.inTransaction {
        val now = System.currentTimeMillis()
        val lotId = insertOrThrow(
            "stock_lots",
            null,
            ContentValues().apply {
                put("name", name.trim())
                put("purchase_quantity_milli", quantityMilli)
                put("unit", unit)
                put("location", location)
                put("purchased_on", purchasedOn?.takeIf(String::isNotBlank))
                put("expires_on", expiresOn?.takeIf(String::isNotBlank))
                put("created_at", now)
            },
        )
        insertEvent(this, lotId, "ADD", quantityMilli, "Added", now)
        lotId
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

    fun listPantry(): List<PantryItem> {
        val sql = """
            SELECT l.id, l.name, l.unit, l.location, l.purchased_on, l.expires_on,
                   COALESCE(SUM(e.quantity_milli), 0) AS balance
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
                            purchasedOn = cursor.getStringOrNull(4),
                            expiresOn = cursor.getStringOrNull(5),
                            quantityMilli = cursor.getLong(6),
                        ),
                    )
                }
            }
        }
    }

    fun saveMeal(meal: MealProposal): Long = writableDatabase.insertOrThrow(
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

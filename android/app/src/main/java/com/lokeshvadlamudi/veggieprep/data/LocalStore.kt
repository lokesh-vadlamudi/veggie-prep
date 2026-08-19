package com.lokeshvadlamudi.veggieprep.data

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import java.util.UUID

class LocalStore(context: Context) : SQLiteOpenHelper(context, "veggie_prep.db", null, 1) {
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
                created_at INTEGER NOT NULL
            )
            """.trimIndent(),
        )
        db.execSQL("CREATE INDEX inventory_events_lot ON inventory_events(lot_id, created_at)")
        db.execSQL("CREATE INDEX stock_lots_expiry ON stock_lots(expires_on)")
    }

    override fun onConfigure(db: SQLiteDatabase) {
        super.onConfigure(db)
        db.setForeignKeyConstraintsEnabled(true)
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit

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
                        createdAt = cursor.getLong(cursor.getColumnIndexOrThrow("created_at")),
                    ),
                )
            }
        }
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

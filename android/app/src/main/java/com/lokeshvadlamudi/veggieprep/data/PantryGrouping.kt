package com.lokeshvadlamudi.veggieprep.data

data class PantryGroup(
    val summary: PantryItem,
    val lots: List<PantryItem>,
)

fun groupMatchingPantryItems(pantry: List<PantryItem>): List<PantryGroup> = pantry
    .groupBy { item ->
        PantryGroupKey(
            food = IndianIngredientCatalog.canonicalKey(item.name),
            unit = item.unit,
            location = item.location,
            expiresOn = item.expiresOn,
            icon = item.icon ?: IndianIngredientCatalog.find(item.name)?.visual ?: "🧺",
        )
    }
    .values
    .map { lots ->
        PantryGroup(
            summary = lots.first().copy(
                quantityMilli = lots.sumOf(PantryItem::quantityMilli),
                expiryEstimated = lots.any(PantryItem::expiryEstimated),
                quantityEstimated = lots.any(PantryItem::quantityEstimated),
            ),
            lots = lots,
        )
    }

private data class PantryGroupKey(
    val food: String,
    val unit: String,
    val location: String,
    val expiresOn: String?,
    val icon: String,
)

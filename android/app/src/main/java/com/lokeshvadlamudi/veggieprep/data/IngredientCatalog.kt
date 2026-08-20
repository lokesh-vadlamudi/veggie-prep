package com.lokeshvadlamudi.veggieprep.data

import java.time.LocalDate
import java.util.Locale

data class CatalogIngredient(
    val id: String,
    val name: String,
    val visual: String,
    val category: String,
    val aliases: List<String>,
    val defaultQuantity: String,
    val defaultUnit: String,
    val defaultStorage: String,
    val suggestedShelfLifeDays: Long,
) {
    fun suggestedExpiry(purchasedOn: LocalDate = LocalDate.now()): String =
        purchasedOn.plusDays(suggestedShelfLifeDays).toString()
}

object IndianIngredientCatalog {
    val items: List<CatalogIngredient> = listOf(
        item("spinach", "Spinach", "🥬", "Greens", "200", "g", "fridge", 4, "palak", "keerai", "palakura"),
        item("fenugreek-leaves", "Fenugreek leaves", "🌿", "Greens", "1", "count", "fridge", 3, "methi", "menthi kura"),
        item("coriander-leaves", "Coriander leaves", "🌿", "Greens", "1", "count", "fridge", 5, "cilantro", "dhania", "kothimeera", "malli"),
        item("mint", "Mint", "🌿", "Greens", "1", "count", "fridge", 5, "pudina"),
        item("amaranth-leaves", "Amaranth leaves", "🥬", "Greens", "1", "count", "fridge", 3, "chaulai", "thotakura", "keerai"),
        item("mustard-greens", "Mustard greens", "🥬", "Greens", "1", "count", "fridge", 4, "sarson", "sarson ka saag"),
        item("curry-leaves", "Curry leaves", "🌿", "Greens", "1", "count", "fridge", 7, "kadi patta", "karivepaku", "karuveppilai"),
        item("drumstick-leaves", "Drumstick leaves", "🌿", "Greens", "1", "count", "fridge", 3, "moringa leaves", "munagaku"),

        item("tomato", "Tomatoes", "🍅", "Vegetables", "4", "count", "fridge", 7, "tamatar", "tamata"),
        item("onion", "Onions", "🧅", "Vegetables", "4", "count", "pantry", 21, "pyaz", "ullipaya", "vengayam"),
        item("potato", "Potatoes", "🥔", "Vegetables", "4", "count", "pantry", 21, "aloo", "bangaladumpa", "urulai"),
        item("eggplant", "Eggplant", "🍆", "Vegetables", "2", "count", "fridge", 5, "brinjal", "baingan", "vankaya", "kathirikai"),
        item("okra", "Okra", "🌱", "Vegetables", "250", "g", "fridge", 4, "bhindi", "lady finger", "bendakaya", "vendakkai"),
        item("cauliflower", "Cauliflower", "🥦", "Vegetables", "1", "count", "fridge", 6, "gobi", "phool gobi"),
        item("cabbage", "Cabbage", "🥬", "Vegetables", "1", "count", "fridge", 10, "patta gobi", "kosu"),
        item("carrot", "Carrots", "🥕", "Vegetables", "4", "count", "fridge", 14, "gajar"),
        item("beetroot", "Beetroot", "🫜", "Vegetables", "2", "count", "fridge", 14, "beet", "chukandar"),
        item("radish", "Radish", "🫜", "Vegetables", "2", "count", "fridge", 7, "mooli", "mullangi"),
        item("bottle-gourd", "Bottle gourd", "🥒", "Vegetables", "1", "count", "fridge", 7, "lauki", "sorakaya", "suraikkai", "doodhi"),
        item("ridge-gourd", "Ridge gourd", "🥒", "Vegetables", "2", "count", "fridge", 5, "turai", "beerakaya", "peerkangai"),
        item("bitter-gourd", "Bitter gourd", "🥒", "Vegetables", "2", "count", "fridge", 5, "karela", "kakarakaya", "pavakkai"),
        item("snake-gourd", "Snake gourd", "🥒", "Vegetables", "1", "count", "fridge", 5, "padwal", "potlakaya", "pudalangai"),
        item("ash-gourd", "Ash gourd", "🎃", "Vegetables", "1", "count", "fridge", 10, "petha", "boodida gummadi", "poosanikai"),
        item("pumpkin", "Pumpkin", "🎃", "Vegetables", "1", "kg", "fridge", 7, "kaddu", "gummadikaya", "parangikkai"),
        item("drumstick", "Drumsticks", "🌿", "Vegetables", "4", "count", "fridge", 5, "moringa pods", "munagakaya", "murungakkai"),
        item("green-beans", "Green beans", "🫛", "Vegetables", "250", "g", "fridge", 6, "beans", "french beans"),
        item("cluster-beans", "Cluster beans", "🫛", "Vegetables", "250", "g", "fridge", 5, "gawar", "goruchikkudu", "kothavarangai"),
        item("green-peas", "Green peas", "🫛", "Vegetables", "250", "g", "fridge", 5, "matar", "batani", "pattani"),
        item("capsicum", "Capsicum", "🫑", "Vegetables", "2", "count", "fridge", 7, "bell pepper", "shimla mirch"),
        item("green-chilli", "Green chillies", "🌶️", "Vegetables", "100", "g", "fridge", 10, "hari mirch", "pachi mirapakaya", "pachai milagai"),
        item("cucumber", "Cucumber", "🥒", "Vegetables", "2", "count", "fridge", 7, "kheera", "dosakaya", "vellarikai"),
        item("raw-banana", "Raw bananas", "🍌", "Vegetables", "2", "count", "pantry", 5, "plantain", "kachcha kela", "aratikaya", "vazhakkai"),
        item("raw-mango", "Raw mango", "🥭", "Vegetables", "2", "count", "fridge", 7, "kairi", "mamidikaya", "manga"),
        item("sweet-potato", "Sweet potato", "🍠", "Vegetables", "500", "g", "pantry", 14, "shakarkandi", "chilakada dumpa", "sakkaravalli"),
        item("taro-root", "Taro root", "🫜", "Vegetables", "500", "g", "pantry", 10, "arbi", "chamagadda", "seppankizhangu"),
        item("yam", "Yam", "🫜", "Vegetables", "500", "g", "pantry", 14, "suran", "kanda", "senaikizhangu"),
        item("mushroom", "Mushrooms", "🍄", "Vegetables", "200", "g", "fridge", 4, "button mushroom"),

        item("toor-dal", "Toor dal", "🫘", "Dals & beans", "500", "g", "pantry", 180, "arhar dal", "pigeon peas", "kandi pappu", "thuvaram paruppu"),
        item("moong-dal", "Moong dal", "🫘", "Dals & beans", "500", "g", "pantry", 180, "mung dal", "pesara pappu", "paasi paruppu"),
        item("masoor-dal", "Masoor dal", "🫘", "Dals & beans", "500", "g", "pantry", 180, "red lentils", "erra pappu"),
        item("chana-dal", "Chana dal", "🫘", "Dals & beans", "500", "g", "pantry", 180, "split chickpeas", "senaga pappu", "kadalai paruppu"),
        item("urad-dal", "Urad dal", "🫘", "Dals & beans", "500", "g", "pantry", 180, "black gram", "minapappu", "ulutham paruppu"),
        item("whole-moong", "Whole green gram", "🫘", "Dals & beans", "500", "g", "pantry", 180, "sabut moong", "pesalu", "pachai payaru"),
        item("whole-urad", "Whole black gram", "🫘", "Dals & beans", "500", "g", "pantry", 180, "sabut urad", "minumulu"),
        item("chickpeas", "Chickpeas", "🫘", "Dals & beans", "500", "g", "pantry", 180, "kabuli chana", "garbanzo", "senagalu", "kondakadalai"),
        item("black-chickpeas", "Black chickpeas", "🫘", "Dals & beans", "500", "g", "pantry", 180, "kala chana", "brown chana"),
        item("kidney-beans", "Kidney beans", "🫘", "Dals & beans", "500", "g", "pantry", 180, "rajma"),
        item("black-eyed-peas", "Black-eyed peas", "🫘", "Dals & beans", "500", "g", "pantry", 180, "lobia", "alasandalu", "karamani"),
        item("horse-gram", "Horse gram", "🫘", "Dals & beans", "500", "g", "pantry", 180, "kulith", "ulavalu", "kollu"),
        item("moth-beans", "Moth beans", "🫘", "Dals & beans", "500", "g", "pantry", 180, "matki"),
        item("soy-chunks", "Soya chunks", "🫘", "Dals & beans", "200", "g", "pantry", 180, "meal maker", "soy nuggets"),

        item("rice", "Rice", "🍚", "Grains & flours", "1", "kg", "pantry", 180, "chawal", "biyyam", "arisi"),
        item("basmati-rice", "Basmati rice", "🍚", "Grains & flours", "1", "kg", "pantry", 180, "basmati"),
        item("brown-rice", "Brown rice", "🍚", "Grains & flours", "1", "kg", "pantry", 180),
        item("poha", "Poha", "🍚", "Grains & flours", "500", "g", "pantry", 120, "flattened rice", "aval", "atukulu"),
        item("puffed-rice", "Puffed rice", "🍘", "Grains & flours", "250", "g", "pantry", 60, "murmura", "borugulu", "pori"),
        item("wheat-flour", "Whole wheat flour", "🌾", "Grains & flours", "1", "kg", "pantry", 90, "atta", "godhuma pindi"),
        item("maida", "All-purpose flour", "🌾", "Grains & flours", "1", "kg", "pantry", 90, "maida", "plain flour"),
        item("besan", "Gram flour", "🌾", "Grains & flours", "500", "g", "pantry", 90, "besan", "chickpea flour", "senaga pindi"),
        item("rice-flour", "Rice flour", "🌾", "Grains & flours", "500", "g", "pantry", 90, "chawal atta", "biyyam pindi"),
        item("semolina", "Semolina", "🌾", "Grains & flours", "500", "g", "pantry", 90, "sooji", "rava", "upma rava"),
        item("ragi", "Ragi flour", "🌾", "Millets", "500", "g", "pantry", 90, "finger millet", "nachni", "ragulu", "kezhvaragu"),
        item("jowar", "Jowar flour", "🌾", "Millets", "500", "g", "pantry", 90, "sorghum", "jonna pindi", "cholam"),
        item("bajra", "Bajra flour", "🌾", "Millets", "500", "g", "pantry", 90, "pearl millet", "sajja pindi", "kambu"),
        item("foxtail-millet", "Foxtail millet", "🌾", "Millets", "500", "g", "pantry", 120, "kangni", "korralu", "thinai"),
        item("little-millet", "Little millet", "🌾", "Millets", "500", "g", "pantry", 120, "samai", "samalu"),
        item("vermicelli", "Vermicelli", "🍜", "Grains & flours", "500", "g", "pantry", 120, "seviyan", "semiya"),

        item("paneer", "Paneer", "🧀", "Dairy", "200", "g", "fridge", 4),
        item("milk", "Milk", "🥛", "Dairy", "1", "l", "fridge", 5, "doodh", "paalu", "paal"),
        item("curd", "Curd", "🥣", "Dairy", "500", "g", "fridge", 7, "yogurt", "dahi", "perugu", "thayir"),
        item("buttermilk", "Buttermilk", "🥛", "Dairy", "1", "l", "fridge", 4, "chaas", "majjiga", "mor"),
        item("butter", "Butter", "🧈", "Dairy", "200", "g", "fridge", 30, "makhan", "venna"),
        item("ghee", "Ghee", "🧈", "Dairy", "500", "g", "pantry", 180, "clarified butter", "neyyi", "nei"),
        item("coconut-milk", "Coconut milk", "🥥", "Dairy", "400", "ml", "fridge", 3, "nariyal milk"),

        item("ginger", "Ginger", "🫚", "Aromatics", "100", "g", "fridge", 14, "adrak", "allam", "inji"),
        item("garlic", "Garlic", "🧄", "Aromatics", "2", "count", "pantry", 21, "lahsun", "vellulli", "poondu"),
        item("tamarind", "Tamarind", "🟤", "Aromatics", "200", "g", "pantry", 180, "imli", "chintapandu", "puli"),
        item("fresh-coconut", "Fresh coconut", "🥥", "Aromatics", "1", "count", "fridge", 5, "nariyal", "kobbari", "thengai"),

        item("cumin", "Cumin seeds", "🫙", "Spices", "100", "g", "pantry", 365, "jeera", "jeelakarra", "seeragam"),
        item("mustard-seeds", "Mustard seeds", "🫙", "Spices", "100", "g", "pantry", 365, "rai", "sarson", "avalu", "kadugu"),
        item("turmeric", "Turmeric powder", "🟡", "Spices", "100", "g", "pantry", 365, "haldi", "pasupu", "manjal"),
        item("chilli-powder", "Red chilli powder", "🌶️", "Spices", "100", "g", "pantry", 365, "lal mirch", "karam", "milagai thool"),
        item("coriander-powder", "Coriander powder", "🫙", "Spices", "100", "g", "pantry", 365, "dhania powder"),
        item("garam-masala", "Garam masala", "🫙", "Spices", "100", "g", "pantry", 240),
        item("sambar-powder", "Sambar powder", "🫙", "Spices", "100", "g", "pantry", 240, "sambar podi"),
        item("rasam-powder", "Rasam powder", "🫙", "Spices", "100", "g", "pantry", 240, "rasam podi"),
        item("fenugreek-seeds", "Fenugreek seeds", "🫙", "Spices", "100", "g", "pantry", 365, "methi dana", "menthulu", "vendhayam"),
        item("fennel", "Fennel seeds", "🫙", "Spices", "100", "g", "pantry", 365, "saunf", "sombu"),
        item("carom", "Carom seeds", "🫙", "Spices", "100", "g", "pantry", 365, "ajwain", "vamu", "omam"),
        item("black-pepper", "Black pepper", "⚫", "Spices", "100", "g", "pantry", 365, "kali mirch", "miriyalu", "milagu"),
        item("cardamom", "Cardamom", "🫙", "Spices", "50", "g", "pantry", 365, "elaichi", "elakulu", "elakkai"),
        item("cloves", "Cloves", "🫙", "Spices", "50", "g", "pantry", 365, "laung", "lavangam", "kirambu"),
        item("cinnamon", "Cinnamon", "🪵", "Spices", "50", "g", "pantry", 365, "dalchini", "dalchina chekka", "pattai"),
        item("asafoetida", "Asafoetida", "🫙", "Spices", "50", "g", "pantry", 365, "hing", "inguva", "perungayam"),
        item("bay-leaf", "Bay leaves", "🍂", "Spices", "20", "g", "pantry", 365, "tej patta", "biriyani aaku"),
        item("salt", "Salt", "🧂", "Spices", "1", "kg", "pantry", 730, "namak", "uppu"),

        item("cooking-oil", "Cooking oil", "🫗", "Oils", "1", "l", "pantry", 180, "vegetable oil", "sunflower oil"),
        item("mustard-oil", "Mustard oil", "🫗", "Oils", "1", "l", "pantry", 180, "sarson oil"),
        item("coconut-oil", "Coconut oil", "🥥", "Oils", "1", "l", "pantry", 180),
        item("sesame-oil", "Sesame oil", "🫗", "Oils", "1", "l", "pantry", 180, "gingelly oil", "til oil", "nuvvula noone", "nallennai"),

        item("banana", "Bananas", "🍌", "Fruits", "6", "count", "pantry", 5, "kela", "arati pandu", "vazhaipazham"),
        item("apple", "Apples", "🍎", "Fruits", "4", "count", "fridge", 21, "seb"),
        item("mango", "Mangoes", "🥭", "Fruits", "4", "count", "pantry", 5, "aam", "mamidi pandu", "mambazham"),
        item("orange", "Oranges", "🍊", "Fruits", "6", "count", "fridge", 14, "santra", "kamala"),
        item("lemon", "Lemons", "🍋", "Fruits", "6", "count", "fridge", 21, "nimbu", "nimma", "elumichai"),
        item("guava", "Guavas", "🍐", "Fruits", "4", "count", "fridge", 5, "amrood", "jama pandu", "koyya"),
        item("papaya", "Papaya", "🍈", "Fruits", "1", "count", "fridge", 5, "papita", "boppayi", "pappali"),
        item("pomegranate", "Pomegranates", "🔴", "Fruits", "2", "count", "fridge", 14, "anar", "danimmakaya", "mathulai"),
        item("grapes", "Grapes", "🍇", "Fruits", "500", "g", "fridge", 7, "angoor", "draksha"),
        item("watermelon", "Watermelon", "🍉", "Fruits", "1", "count", "fridge", 7, "tarbooz", "puchakaya", "tharboosani"),

        item("peanuts", "Peanuts", "🥜", "Nuts & seeds", "500", "g", "pantry", 120, "groundnuts", "moongphali", "verusenaga", "verkadalai"),
        item("cashews", "Cashews", "🥜", "Nuts & seeds", "250", "g", "pantry", 120, "kaju", "jeedipappu", "mundhiri"),
        item("almonds", "Almonds", "🥜", "Nuts & seeds", "250", "g", "pantry", 120, "badam"),
        item("sesame-seeds", "Sesame seeds", "⚪", "Nuts & seeds", "200", "g", "pantry", 180, "til", "nuvvulu", "ellu"),
        item("flax-seeds", "Flax seeds", "🫘", "Nuts & seeds", "200", "g", "pantry", 120, "alsi", "avise ginjalu"),
        item("jaggery", "Jaggery", "🟤", "Sweeteners", "500", "g", "pantry", 180, "gur", "bellam", "vellam"),
        item("sugar", "Sugar", "🍚", "Sweeteners", "1", "kg", "pantry", 365, "cheeni", "sakkarai"),
    ) + expandedHouseholdFoods()

    private val byAlias: Map<String, CatalogIngredient> = buildMap {
        items.forEach { ingredient ->
            (ingredient.aliases + ingredient.name + ingredient.id).forEach { alias ->
                val normalized = normalize(alias)
                putIfAbsent(normalized, ingredient)
                putIfAbsent(singularize(normalized), ingredient)
            }
        }
    }

    fun search(query: String): List<CatalogIngredient> {
        val needle = normalize(query)
        if (needle.isBlank()) return items
        return items.mapNotNull { ingredient ->
            val values = ingredient.aliases + ingredient.name + ingredient.category
            val score = when {
                values.any { normalize(it) == needle } -> 0
                values.any { normalize(it).startsWith(needle) } -> 1
                values.any { normalize(it).contains(needle) } -> 2
                else -> return@mapNotNull null
            }
            score to ingredient
        }.sortedWith(compareBy<Pair<Int, CatalogIngredient>> { it.first }.thenBy { it.second.name })
            .map { it.second }
    }

    fun find(name: String): CatalogIngredient? {
        val normalized = normalize(name)
        return byAlias[normalized] ?: byAlias[singularize(normalized)]
    }

    fun canonicalKey(name: String): String = find(name)?.id ?: normalize(name).replace(' ', '-')

    fun isSnackCategory(category: String): Boolean = category in setOf(
        "Snacks",
        "Indian snacks",
        "Bakery & desserts",
        "Indian sweets",
    )

    fun isSnack(name: String, storedCategory: String = ""): Boolean =
        isSnackCategory(storedCategory) || find(name)?.let { isSnackCategory(it.category) } == true

    private fun item(
        id: String,
        name: String,
        visual: String,
        category: String,
        defaultQuantity: String,
        defaultUnit: String,
        defaultStorage: String,
        shelfLifeDays: Long,
        vararg aliases: String,
    ) = CatalogIngredient(
        id = id,
        name = name,
        visual = visual,
        category = category,
        aliases = aliases.toList(),
        defaultQuantity = defaultQuantity,
        defaultUnit = defaultUnit,
        defaultStorage = defaultStorage,
        suggestedShelfLifeDays = shelfLifeDays,
    )

    private fun normalize(value: String): String = value
        .lowercase(Locale.ROOT)
        .replace(Regex("[^a-z0-9]+"), " ")
        .trim()

    private fun singularize(value: String): String = when {
        value.length <= 4 -> value
        value.endsWith("ies") -> value.dropLast(3) + "y"
        value.endsWith("oes") -> value.dropLast(2)
        value.endsWith("s") && !value.endsWith("ss") -> value.dropLast(1)
        else -> value
    }
}

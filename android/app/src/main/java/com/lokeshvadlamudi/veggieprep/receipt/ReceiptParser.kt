package com.lokeshvadlamudi.veggieprep.receipt

import com.lokeshvadlamudi.veggieprep.data.CatalogIngredient
import com.lokeshvadlamudi.veggieprep.data.IndianIngredientCatalog
import com.lokeshvadlamudi.veggieprep.data.parseMilli
import java.security.MessageDigest
import java.time.LocalDate
import java.util.Locale
import java.util.UUID

object ReceiptParser {
    private val moneyAtEnd = Regex("""^(.*?)\s+(?:[${'$'}S]\s*)?-?\d+\s*[.,]\s*\d{2}[A-Z]?$""", RegexOption.IGNORE_CASE)
    private val quantityLine = Regex("""^(\d+(?:[.]\d+)?)\s*@\s*(?:[${'$'}S]\s*)?\d+\s*[.,]\s*\d{2}$""", RegexOption.IGNORE_CASE)
    private val packageSize = Regex("""\b(\d+(?:[.]\d+)?)\s*(LBS?|LB|KG|G|OZ|ML|L)\b""", RegexOption.IGNORE_CASE)
    private val datePattern = Regex("""\b(\d{1,2})[/-](\d{1,2})[/-](\d{2}|\d{4})\b""")
    private val stopRows = listOf(
        "items in transaction",
        "balance to pay",
        "subtotal",
        "payment card",
        "visa credit",
        "customer copy",
    )
    private val ignoredLabels = listOf(
        "sale transaction",
        "grocery non taxable",
        "grocery non-taxable",
        "tax",
        "total",
        "balance",
        "visa",
        "change",
        "cash",
        "coupon",
        "discount",
    )
    private val matchingNoise = setOf(
        "a", "bag", "bags", "org", "organic", "whole", "whol", "pint", "each", "medium", "mediu",
        "mediterranean", "roasted", "red", "sauce", "fresh", "large", "small", "gold", "golden",
    )

    fun parse(
        rows: List<ReceiptTextRow>,
        today: LocalDate = LocalDate.now(),
    ): ReceiptDraft {
        val normalizedRows = rows
            .map { it.copy(text = it.text.replace(Regex("\\s+"), " ").trim()) }
            .filter { it.text.isNotBlank() }
        val merchant = detectMerchant(normalizedRows.map { it.text })
        val purchasedOn = detectDate(normalizedRows.map { it.text }) ?: today
        val saleStart = normalizedRows.indexOfFirst { normalize(it.text).contains("sale transaction") }
        val body = normalizedRows.drop(if (saleStart >= 0) saleStart + 1 else 0)

        val candidates = mutableListOf<ReceiptCandidate>()
        var skipped = 0
        body.takeWhile { row ->
            val normalized = normalize(row.text)
            stopRows.none { normalized.contains(it) }
        }.forEach { row ->
            val normalized = normalize(row.text)

            val quantityMatch = quantityLine.matchEntire(row.text.replace(',', '.'))
            if (quantityMatch != null) {
                val count = parseMilli(quantityMatch.groupValues[1]) ?: 1_000L
                val previousIndex = candidates.lastIndex
                if (previousIndex >= 0) {
                    candidates[previousIndex] = applyPackageCount(candidates[previousIndex], count)
                } else {
                    skipped++
                }
                return@forEach
            }

            val priceMatch = moneyAtEnd.matchEntire(row.text.replace(',', '.'))
            val rawLabel = priceMatch?.groupValues?.get(1)?.trim().orEmpty()
            if (rawLabel.isBlank()) return@forEach
            val cleanLabel = rawLabel.replace(Regex("^[A-Z]-", RegexOption.IGNORE_CASE), "").trim()
            val cleanNormalized = normalize(cleanLabel)
            if (ignoredLabels.any { cleanNormalized == it || cleanNormalized.startsWith("$it ") }) {
                if (cleanNormalized.contains("grocery non taxable")) {
                    candidates += unknownCandidate(
                        label = cleanLabel,
                        purchasedOn = purchasedOn,
                        confidence = ReceiptConfidence.LOW,
                        reason = "The receipt did not name this product.",
                    )
                } else {
                    skipped++
                }
                return@forEach
            }
            if (looksLikeReceiptMetadata(cleanNormalized)) {
                skipped++
                return@forEach
            }

            candidates += candidateFor(cleanLabel, purchasedOn, row.confidence)
        }

        val fingerprintMaterial = buildString {
            append(merchant.lowercase(Locale.ROOT)).append('|').append(purchasedOn)
            candidates.forEach {
                append('|').append(normalize(it.rawLabel))
                append(':').append(it.quantityMilli).append(':').append(it.unit)
            }
        }
        return ReceiptDraft(
            fingerprint = sha256(fingerprintMaterial),
            merchant = merchant,
            purchasedOn = purchasedOn.toString(),
            candidates = candidates,
            skippedLineCount = skipped,
        )
    }

    fun revise(
        candidate: ReceiptCandidate,
        name: String,
        quantityText: String,
        unit: String,
        location: String,
        expiresOn: String,
        included: Boolean,
    ): ReceiptCandidate {
        val quantity = parseMilli(quantityText)
            ?: throw IllegalArgumentException("Enter a positive quantity with up to 3 decimal places.")
        require(quantity > 0) { "Enter a positive quantity." }
        val expiry = expiresOn.trim()
        if (expiry.isNotEmpty()) LocalDate.parse(expiry)
        val catalog = bestCatalogMatch(name).ingredient
        return candidate.copy(
            name = name.trim(),
            quantityMilli = quantity,
            unit = unit,
            location = location,
            category = catalog?.category ?: candidate.category,
            expiresOn = expiry,
            expiryEstimated = expiry.isNotEmpty() && expiry == candidate.expiresOn && candidate.expiryEstimated,
            quantityEstimated = false,
            confidence = if (name.isNotBlank()) ReceiptConfidence.HIGH else candidate.confidence,
            included = included,
            matchReason = "Reviewed by you",
        )
    }

    private fun candidateFor(label: String, purchasedOn: LocalDate, ocrConfidence: Float): ReceiptCandidate {
        val match = bestCatalogMatch(label)
        if (match.ingredient == null) {
            return unknownCandidate(
                label = label,
                purchasedOn = purchasedOn,
                confidence = ReceiptConfidence.LOW,
                reason = "Choose a food or edit this receipt line.",
            )
        }
        val ingredient = match.ingredient
        val detectedSize = detectedPackageSize(label, ingredient.defaultUnit)
        val defaultQuantity = parseMilli(ingredient.defaultQuantity) ?: 1_000L
        val quantity = detectedSize?.first ?: defaultQuantity
        val unit = detectedSize?.second ?: ingredient.defaultUnit
        val confidence = when {
            ocrConfidence < 0.55f -> ReceiptConfidence.REVIEW
            match.score >= 0.9 -> ReceiptConfidence.HIGH
            else -> ReceiptConfidence.REVIEW
        }
        return ReceiptCandidate(
            id = UUID.randomUUID().toString(),
            rawLabel = label.take(160),
            name = ingredient.name,
            quantityMilli = quantity,
            unit = unit,
            location = ingredient.defaultStorage,
            category = ingredient.category,
            expiresOn = ingredient.suggestedExpiry(purchasedOn),
            expiryEstimated = true,
            quantityEstimated = detectedSize == null,
            confidence = confidence,
            included = confidence != ReceiptConfidence.LOW,
            matchReason = if (confidence == ReceiptConfidence.HIGH) "Matched to ${ingredient.name}" else "Please verify this match",
        )
    }

    private fun unknownCandidate(
        label: String,
        purchasedOn: LocalDate,
        confidence: ReceiptConfidence,
        reason: String,
    ) = ReceiptCandidate(
        id = UUID.randomUUID().toString(),
        rawLabel = label.take(160),
        name = label.lowercase(Locale.ROOT).replaceFirstChar(Char::uppercase).take(80),
        quantityMilli = 1_000,
        unit = "count",
        location = "pantry",
        category = "Other",
        expiresOn = "",
        expiryEstimated = false,
        quantityEstimated = true,
        confidence = confidence,
        included = false,
        matchReason = reason,
    )

    private fun applyPackageCount(candidate: ReceiptCandidate, packageCountMilli: Long): ReceiptCandidate {
        val multiplied = Math.multiplyExact(candidate.quantityMilli, packageCountMilli) / 1_000L
        return candidate.copy(
            quantityMilli = multiplied,
            quantityEstimated = candidate.quantityEstimated,
            matchReason = "${candidate.matchReason}; ${formatCount(packageCountMilli)} packages",
        )
    }

    private fun formatCount(milli: Long): String = if (milli % 1_000L == 0L) (milli / 1_000L).toString() else (milli / 1_000.0).toString()

    private data class CatalogMatch(val ingredient: CatalogIngredient?, val score: Double)

    private fun bestCatalogMatch(label: String): CatalogMatch {
        val normalized = normalize(label)
        val labelTokens = normalized.split(' ').filter { it.isNotBlank() }.toSet()
        val meaningful = labelTokens.filterNot { token ->
            token in matchingNoise || token.toDoubleOrNull() != null || token in setOf("lb", "lbs", "kg", "g", "oz", "ml", "l")
        }.toSet()
        var best: CatalogIngredient? = null
        var bestScore = 0.0
        var secondScore = 0.0
        IndianIngredientCatalog.items.forEach { ingredient ->
            val phrases = ingredient.aliases + ingredient.name + ingredient.id.replace('-', ' ')
            val score = phrases.maxOf { phrase ->
                val candidatePhrase = normalize(phrase)
                val phraseTokens = candidatePhrase.split(' ').filter { it.isNotBlank() }.toSet()
                when {
                    candidatePhrase.isNotBlank() && Regex("(?:^| )${Regex.escape(candidatePhrase)}(?: |$)").containsMatchIn(normalized) ->
                        1.0 + (phraseTokens.size * 0.01)
                    phraseTokens.isEmpty() || meaningful.isEmpty() -> 0.0
                    else -> {
                        val overlap = meaningful.intersect(phraseTokens).size.toDouble()
                        val recall = overlap / phraseTokens.size
                        val precision = overlap / meaningful.size
                        (recall * 0.75) + (precision * 0.25)
                    }
                }
            }
            if (score > bestScore) {
                secondScore = bestScore
                bestScore = score
                best = ingredient
            } else if (score > secondScore) {
                secondScore = score
            }
        }
        val accepted = bestScore >= 0.55 && (bestScore >= 0.9 || bestScore - secondScore >= 0.12)
        return CatalogMatch(best.takeIf { accepted }, bestScore)
    }

    private fun detectedPackageSize(label: String, expectedUnit: String): Pair<Long, String>? {
        if (Regex("\\bEACH\\b", RegexOption.IGNORE_CASE).containsMatchIn(label)) return 1_000L to "count"
        val match = packageSize.find(label) ?: return null
        val quantity = parseMilli(match.groupValues[1]) ?: return null
        return when (match.groupValues[2].uppercase(Locale.ROOT)) {
            "LB", "LBS" -> quantity to "lb"
            "OZ" -> quantity to "oz"
            "KG" -> quantity to "kg"
            "G" -> quantity to "g"
            "L" -> if (expectedUnit in setOf("g", "kg")) {
                quantity to "lb"
            } else {
                quantity to "l"
            }
            "ML" -> quantity to "ml"
            else -> null
        }
    }

    private fun detectMerchant(lines: List<String>): String {
        val joined = lines.take(20).joinToString(" ").lowercase(Locale.ROOT)
        return when {
            "trader joe" in joined -> "Trader Joe's"
            "whole foods" in joined -> "Whole Foods"
            "costco" in joined -> "Costco"
            "walmart" in joined -> "Walmart"
            "target" in joined -> "Target"
            else -> "Grocery receipt"
        }
    }

    private fun detectDate(lines: List<String>): LocalDate? {
        lines.forEach { line ->
            val match = datePattern.find(line) ?: return@forEach
            val month = match.groupValues[1].toInt()
            val day = match.groupValues[2].toInt()
            val rawYear = match.groupValues[3].toInt()
            val year = if (rawYear < 100) 2_000 + rawYear else rawYear
            runCatching { LocalDate.of(year, month, day) }.getOrNull()?.let { return it }
        }
        return null
    }

    private fun looksLikeReceiptMetadata(value: String): Boolean =
        value.contains("store ") ||
            value.contains("open ") ||
            value.contains("auth code") ||
            value.contains("cardholder") ||
            value.matches(Regex(".*\\b(?:am|pm)\\b.*"))

    private fun normalize(value: String): String = value
        .lowercase(Locale.ROOT)
        .replace('&', ' ')
        .replace(Regex("[^a-z0-9]+"), " ")
        .trim()

    private fun sha256(value: String): String = MessageDigest.getInstance("SHA-256")
        .digest(value.toByteArray())
        .joinToString("") { "%02x".format(it) }
}

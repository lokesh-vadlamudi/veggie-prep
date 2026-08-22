package com.lokeshvadlamudi.veggieprep.receipt

enum class ReceiptConfidence {
    HIGH,
    REVIEW,
    LOW,
}

data class ReceiptTextRow(
    val text: String,
    val confidence: Float = 1f,
)

data class ReceiptCandidate(
    val id: String,
    val rawLabel: String,
    val name: String,
    val quantityMilli: Long,
    val unit: String,
    val location: String,
    val category: String,
    val expiresOn: String,
    val expiryEstimated: Boolean,
    val quantityEstimated: Boolean,
    val confidence: ReceiptConfidence,
    val included: Boolean,
    val matchReason: String,
)

data class ReceiptDraft(
    val fingerprint: String,
    val merchant: String,
    val purchasedOn: String,
    val candidates: List<ReceiptCandidate>,
    val skippedLineCount: Int,
) {
    val includedCount: Int
        get() = candidates.count { it.included }

    val needsReviewCount: Int
        get() = candidates.count { it.confidence != ReceiptConfidence.HIGH }
}

data class ReceiptImportResult(
    val importId: Long,
    val addedCount: Int,
)

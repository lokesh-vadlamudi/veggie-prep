package com.lokeshvadlamudi.veggieprep.receipt

import android.content.Context
import android.graphics.Rect
import android.net.Uri
import com.google.android.gms.tasks.Task
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.Text
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import java.time.LocalDate
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.suspendCancellableCoroutine

object ReceiptOcr {
    suspend fun read(
        context: Context,
        imageUris: List<Uri>,
        today: LocalDate = LocalDate.now(),
    ): ReceiptDraft {
        require(imageUris.isNotEmpty()) { "No receipt image was returned." }
        val recognizer = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
        try {
            val rows = buildList {
                imageUris.forEach { uri ->
                    val image = InputImage.fromFilePath(context, uri)
                    val text = recognizer.process(image).awaitResult()
                    addAll(groupIntoRows(text))
                }
            }
            require(rows.isNotEmpty()) { "No readable text was found. Try brighter light and keep the receipt flat." }
            val draft = ReceiptParser.parse(rows, today)
            require(draft.candidates.isNotEmpty()) {
                "No grocery lines were found. Retake the receipt closer, or choose a clearer photo."
            }
            return draft
        } finally {
            recognizer.close()
        }
    }

    internal fun groupIntoRows(text: Text): List<ReceiptTextRow> {
        data class Piece(val value: String, val box: Rect, val confidence: Float)
        val pieces = text.textBlocks.flatMap { block ->
            block.lines.mapNotNull { line ->
                line.boundingBox?.let { Piece(line.text, it, line.confidence) }
            }
        }.sortedWith(compareBy<Piece> { it.box.centerY() }.thenBy { it.box.left })
        if (pieces.isEmpty()) {
            return text.textBlocks.flatMap { it.lines }.map { ReceiptTextRow(it.text, it.confidence) }
        }

        val groups = mutableListOf<MutableList<Piece>>()
        pieces.forEach { piece ->
            val current = groups.lastOrNull()
            val currentCenter = current?.map { it.box.centerY() }?.average()
            val tolerance = current?.maxOfOrNull { it.box.height() }?.times(0.55) ?: 0.0
            if (current != null && currentCenter != null && kotlin.math.abs(piece.box.centerY() - currentCenter) <= tolerance) {
                current += piece
            } else {
                groups += mutableListOf(piece)
            }
        }
        return groups.map { group ->
            val sorted = group.sortedBy { it.box.left }
            ReceiptTextRow(
                text = sorted.joinToString(" ") { it.value.trim() },
                confidence = sorted.map { it.confidence }.average().toFloat(),
            )
        }
    }
}

private suspend fun <T> Task<T>.awaitResult(): T = suspendCancellableCoroutine { continuation ->
    addOnSuccessListener { result -> if (continuation.isActive) continuation.resume(result) }
    addOnFailureListener { error -> if (continuation.isActive) continuation.resumeWithException(error) }
    addOnCanceledListener { continuation.cancel() }
}

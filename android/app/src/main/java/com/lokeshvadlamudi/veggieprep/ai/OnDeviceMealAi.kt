package com.lokeshvadlamudi.veggieprep.ai

import android.content.Context
import com.google.ai.edge.litertlm.Backend
import com.google.ai.edge.litertlm.ConversationConfig
import com.google.ai.edge.litertlm.Engine
import com.google.ai.edge.litertlm.EngineConfig
import com.google.ai.edge.litertlm.SamplerConfig
import com.google.mlkit.genai.common.DownloadStatus
import com.google.mlkit.genai.common.FeatureStatus
import com.google.mlkit.genai.prompt.Generation
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.withContext

class GeminiNanoMealAi : MealAi {
    override val label: String = "Gemini Nano"

    override suspend fun generate(prompt: String): String {
        val model = Generation.getClient()
        try {
            when (model.checkStatus()) {
                FeatureStatus.UNAVAILABLE -> throw IllegalStateException(
                    "Gemini Nano is not available on this phone. Choose an imported model or a network API.",
                )
                FeatureStatus.DOWNLOADABLE, FeatureStatus.DOWNLOADING -> {
                    model.download().collect { status ->
                        if (status is DownloadStatus.DownloadFailed) {
                            throw IllegalStateException("Gemini Nano could not be downloaded: ${status.e.message}")
                        }
                    }
                }
            }
            return model.generateContent(prompt).candidates.firstOrNull()?.text
                ?: throw IllegalStateException("Gemini Nano returned an empty response.")
        } finally {
            model.close()
        }
    }
}

class LiteRtMealAi(
    private val context: Context,
    private val modelPath: String,
    override val label: String,
) : MealAi {
    override suspend fun generate(prompt: String): String = withContext(Dispatchers.IO) {
        require(modelPath.isNotBlank()) { "Import an on-device model first." }
        val gpuConfig = EngineConfig(
            modelPath = modelPath,
            backend = Backend.GPU(),
            maxNumTokens = 4096,
            cacheDir = context.cacheDir.absolutePath,
        )
        val engine = runCatching {
            Engine(gpuConfig).also { it.initialize() }
        }.getOrElse {
            Engine(
                gpuConfig.copy(backend = Backend.CPU(threadCount = 4)),
            ).also { it.initialize() }
        }
        engine.use {
            val config = ConversationConfig(
                samplerConfig = SamplerConfig(topK = 20, topP = 0.9, temperature = 0.25),
            )
            it.createConversation(config).use { conversation ->
                conversation.sendMessage(prompt, maxOutputToken = 1800).toString()
            }
        }
    }
}

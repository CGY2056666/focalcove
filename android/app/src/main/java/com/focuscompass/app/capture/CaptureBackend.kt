package com.focuscompass.app.capture

import android.content.Context
import com.focuscompass.app.FocusCompassApplication
import com.focuscompass.app.data.FocusRepository

/** Narrow adapter implemented by the data layer; the capture service never logs or persists JPEGs. */
interface CaptureBackend {
    suspend fun uploadFrame(
        sessionId: String,
        jpeg: ByteArray,
        frameId: String,
        capturedAt: Double,
    ): CaptureFrameResult

    suspend fun completeSession(sessionId: String, reason: String): CaptureCompletionResult
}

data class CaptureAlertEvent(
    val eventId: String,
    val title: String = "专注提醒",
    val message: String,
)

data class CaptureFrameResult(
    val classification: String? = null,
    val rollingSummary: String? = null,
    val alertEvent: CaptureAlertEvent? = null,
)

data class CaptureCompletionResult(
    val sessionId: String,
    val reliable: Boolean? = null,
    val focusScore: Double? = null,
    val effectiveCoverage: Double? = null,
    val pointsEarned: Int = 0,
    val reportJson: String? = null,
    val message: String? = null,
)

/** Production mapping for the repository contract owned by the data layer. */
class FocusRepositoryCaptureBackend(
    private val repository: FocusRepository,
) : CaptureBackend {
    override suspend fun uploadFrame(
        sessionId: String,
        jpeg: ByteArray,
        frameId: String,
        capturedAt: Double,
    ): CaptureFrameResult {
        val payload = repository.uploadFrame(sessionId, jpeg, frameId, capturedAt.toString())
        return CaptureFrameResult(
            classification = payload.latestFrame?.status ?: payload.status,
            rollingSummary = payload.rollingSummary,
            alertEvent = payload.alertEvent?.let { event ->
                CaptureAlertEvent(
                    eventId = event.eventId,
                    title = event.title ?: "专注提醒",
                    message = event.message ?: "检测到分心风险，请回到当前目标。",
                )
            },
        )
    }

    override suspend fun completeSession(sessionId: String, reason: String): CaptureCompletionResult {
        val payload = repository.completeSession(sessionId, reason)
        return CaptureCompletionResult(
            sessionId = payload.sessionId,
            reliable = payload.report?.reliable,
            focusScore = payload.report?.focusScore,
            effectiveCoverage = payload.report?.effectiveCoverage ?: payload.report?.coverageRatio,
            pointsEarned = payload.pointsEarned,
            message = payload.report?.summary,
        )
    }
}

/**
 * Process-local dependency hook. Tests may install a fake; production lazily adapts the repository
 * exposed by FocusCompassApplication, including when WorkManager recreates the process.
 */
object CaptureRuntime {
    @Volatile
    private var backend: CaptureBackend? = null

    fun install(backend: CaptureBackend) {
        this.backend = backend
    }

    fun requireBackend(context: Context): CaptureBackend {
        backend?.let { return it }
        val application = context.applicationContext as? FocusCompassApplication
            ?: error("FocusCompassApplication is required for capture")
        return FocusRepositoryCaptureBackend(application.repository).also { backend = it }
    }
}

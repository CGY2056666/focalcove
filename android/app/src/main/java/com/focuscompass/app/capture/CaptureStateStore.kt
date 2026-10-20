package com.focuscompass.app.capture

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update

enum class CapturePhase { IDLE, CAPTURING, COMPLETING, COMPLETED, INTERRUPTED, ERROR }

data class CaptureHealthWarning(
    val consecutiveNearBlackFrames: Int,
    val totalNearBlackFrames: Int,
    val message: String,
)

data class CaptureState(
    val phase: CapturePhase = CapturePhase.IDLE,
    val sessionId: String? = null,
    val remainingSeconds: Long = 0,
    val classification: String? = null,
    val rollingSummary: String? = null,
    val uploadedFrames: Int = 0,
    val skippedFrames: Int = 0,
    val totalNearBlackFrames: Int = 0,
    val captureHealthWarning: CaptureHealthWarning? = null,
    val latestAlert: CaptureAlertEvent? = null,
    val completion: CaptureCompletionResult? = null,
    val message: String? = null,
    val sessionLost: Boolean = false,
)

/** UI-facing process state. Persistent recovery remains the responsibility of the data layer. */
object CaptureStateStore {
    private val mutableState = MutableStateFlow(CaptureState())
    val state: StateFlow<CaptureState> = mutableState.asStateFlow()

    fun reset() {
        mutableState.value = CaptureState()
    }

    internal fun started(sessionId: String, durationSeconds: Long) {
        mutableState.value = CaptureState(
            phase = CapturePhase.CAPTURING,
            sessionId = sessionId,
            remainingSeconds = durationSeconds,
        )
    }

    internal fun tick(remainingSeconds: Long) = update {
        copy(remainingSeconds = remainingSeconds.coerceAtLeast(0))
    }

    internal fun uploaded(result: CaptureFrameResult) = update {
        copy(
            classification = result.classification ?: classification,
            rollingSummary = result.rollingSummary ?: rollingSummary,
            uploadedFrames = uploadedFrames + 1,
            latestAlert = result.alertEvent ?: latestAlert,
        )
    }

    internal fun skipped(message: String? = null) = update {
        copy(skippedFrames = skippedFrames + 1, message = message)
    }

    internal fun nearBlack(signal: NearBlackSignalUpdate) = update {
        val total = totalNearBlackFrames + 1
        val warning = if (signal.state == NearBlackSignalState.CONFIRMED) {
            CaptureHealthWarning(
                consecutiveNearBlackFrames = signal.consecutiveNearBlackFrames,
                totalNearBlackFrames = total,
                message = "连续采集到近黑画面，可能是安全页面或系统投屏已经失效。",
            )
        } else {
            captureHealthWarning
        }
        copy(
            skippedFrames = skippedFrames + 1,
            totalNearBlackFrames = total,
            captureHealthWarning = warning,
            message = warning?.message ?: message,
        )
    }

    internal fun captureRecovered(message: String? = null) = update {
        copy(
            captureHealthWarning = null,
            message = message,
        )
    }

    internal fun captureProblem(message: String) = update {
        val warning = captureHealthWarning ?: CaptureHealthWarning(
            consecutiveNearBlackFrames = 0,
            totalNearBlackFrames = totalNearBlackFrames,
            message = message,
        )
        copy(
            captureHealthWarning = warning.copy(message = message),
            message = message,
        )
    }

    internal fun completing(reason: String) = update {
        copy(phase = CapturePhase.COMPLETING, message = reason)
    }

    internal fun completed(result: CaptureCompletionResult) = update {
        copy(phase = CapturePhase.COMPLETED, remainingSeconds = 0, completion = result)
    }

    internal fun interrupted(message: String, sessionLost: Boolean = false) = update {
        copy(
            phase = CapturePhase.INTERRUPTED,
            remainingSeconds = 0,
            message = message,
            sessionLost = sessionLost,
        )
    }

    internal fun error(message: String) = update {
        copy(phase = CapturePhase.ERROR, message = message)
    }

    private inline fun update(transform: CaptureState.() -> CaptureState) {
        mutableState.update { current -> current.transform() }
    }
}

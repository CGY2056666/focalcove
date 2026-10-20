package com.focuscompass.app.capture

/** Parameters returned by the backend when a focus session starts. */
data class CapturePolicy(
    val firstCaptureImmediate: Boolean = true,
    val intervalMillis: Long = 20_000L,
    val requestTimeoutMillis: Long = 18_000L,
    val maxImageDimension: Int = 1_024,
    val jpegQuality: Int = 72,
) {
    companion object {
        fun sanitized(
            firstCaptureImmediate: Boolean = true,
            intervalMillis: Long = 20_000L,
            requestTimeoutMillis: Long = 18_000L,
            maxImageDimension: Int = 1_024,
            jpegQuality: Int = 72,
        ): CapturePolicy {
            val safeInterval = intervalMillis.coerceIn(5_000L, 300_000L)
            val safeTimeout = requestTimeoutMillis.coerceIn(
                3_000L,
                minOf(60_000L, safeInterval - 1_000L),
            )
            return CapturePolicy(
                firstCaptureImmediate = firstCaptureImmediate,
                intervalMillis = safeInterval,
                requestTimeoutMillis = safeTimeout,
                maxImageDimension = maxImageDimension.coerceIn(256, 2_048),
                jpegQuality = jpegQuality.coerceIn(40, 95),
            )
        }
    }
}

data class PixelSize(val width: Int, val height: Int)

/** Android 14+ must opt out of single-app sharing for whole-display monitoring. */
fun shouldForceDefaultDisplayCapture(sdkInt: Int): Boolean = sdkInt >= 34

enum class FrameUploadFailureAction { SKIP_FRAME, SESSION_LOST, AUTH_EXPIRED, FORBIDDEN }

fun classifyFrameUploadFailure(httpStatus: Int?): FrameUploadFailureAction = when (httpStatus) {
    401 -> FrameUploadFailureAction.AUTH_EXPIRED
    403 -> FrameUploadFailureAction.FORBIDDEN
    404 -> FrameUploadFailureAction.SESSION_LOST
    else -> FrameUploadFailureAction.SKIP_FRAME
}

/** Pure function kept Android-free so image sizing is covered by local tests. */
fun scaleToFit(width: Int, height: Int, maxDimension: Int): PixelSize {
    require(width > 0 && height > 0) { "Image dimensions must be positive" }
    require(maxDimension > 0) { "maxDimension must be positive" }
    val largest = maxOf(width, height)
    if (largest <= maxDimension) return PixelSize(width, height)
    val scale = maxDimension.toDouble() / largest.toDouble()
    return PixelSize(
        width = maxOf(1, (width * scale).toInt()),
        height = maxOf(1, (height * scale).toInt()),
    )
}

/**
 * Fixed-cadence, single-flight sampling gate. Missed sampling points are skipped;
 * they are never queued for later upload.
 */
class FrameSamplingGate(
    private val intervalMillis: Long,
    private val firstCaptureImmediate: Boolean = true,
) {
    private var nextCaptureAtMillis: Long? = null
    private var requestInFlight = false

    init {
        require(intervalMillis > 0) { "intervalMillis must be positive" }
    }

    @Synchronized
    fun tryAcquire(nowMillis: Long): Boolean {
        val dueAt = nextCaptureAtMillis ?: (
            if (firstCaptureImmediate) nowMillis else nowMillis + intervalMillis
        ).also { nextCaptureAtMillis = it }
        if (requestInFlight || nowMillis < dueAt) return false

        requestInFlight = true
        var next = dueAt
        do {
            next += intervalMillis
        } while (next <= nowMillis)
        nextCaptureAtMillis = next
        return true
    }

    @Synchronized
    fun release() {
        requestInFlight = false
    }
}

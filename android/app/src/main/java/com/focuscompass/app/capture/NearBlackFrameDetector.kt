package com.focuscompass.app.capture

import kotlin.math.sqrt

/**
 * Brightness statistics for an evenly sampled, row-major pixel grid.
 *
 * These values describe capture reliability only. They must never be mapped to a focus or
 * distraction result.
 */
data class FrameLumaStatistics(
    val sampleCount: Int,
    val meanLuma: Double,
    val lumaStandardDeviation: Double,
    val extremelyDarkPixelRatio: Double,
    val highlightPixelRatio: Double,
    val detailEdgeRatio: Double,
)

enum class NearBlackVerdict {
    /** The sample is large enough and does not meet every conservative near-black condition. */
    USABLE,

    /** The sample is almost uniformly black and may indicate a stopped screen projection. */
    NEAR_BLACK,

    /** There are too few pixels to make a safe decision. */
    INSUFFICIENT_DATA,
}

data class NearBlackInspection(
    val verdict: NearBlackVerdict,
    val statistics: FrameLumaStatistics,
)

/**
 * Conservative thresholds for identifying capture failure frames.
 *
 * The defaults intentionally require all conditions to pass. In particular, visible text,
 * controls, dark UI panels, and detailed dark video scenes should make at least one condition
 * fail and therefore remain [NearBlackVerdict.USABLE].
 */
data class NearBlackThresholds(
    val minimumSampleCount: Int = 256,
    val extremelyDarkLuma: Int = 10,
    val highlightLuma: Int = 48,
    val detailLumaDelta: Int = 8,
    val maximumMeanLuma: Double = 3.0,
    val maximumLumaStandardDeviation: Double = 4.0,
    val minimumExtremelyDarkPixelRatio: Double = 0.99,
    val maximumHighlightPixelRatio: Double = 0.001,
    val maximumDetailEdgeRatio: Double = 0.003,
) {
    init {
        require(minimumSampleCount > 0)
        require(extremelyDarkLuma in 0..255)
        require(highlightLuma in (extremelyDarkLuma + 1)..255)
        require(detailLumaDelta in 1..255)
        require(maximumMeanLuma in 0.0..255.0)
        require(maximumLumaStandardDeviation in 0.0..255.0)
        require(minimumExtremelyDarkPixelRatio in 0.0..1.0)
        require(maximumHighlightPixelRatio in 0.0..1.0)
        require(maximumDetailEdgeRatio in 0.0..1.0)
    }
}

/**
 * Android-free detector for an evenly sampled ARGB pixel grid.
 *
 * Callers should pass a modest grid such as 32x32 or 48x48. [FocusCaptureService] samples the
 * central 80% of the captured frame so letterboxing and system bars do not dominate the
 * statistics. Alpha is deliberately ignored because MediaProjection supplies opaque RGB content.
 */
class NearBlackFrameDetector(
    private val thresholds: NearBlackThresholds = NearBlackThresholds(),
) {
    fun inspectArgb(
        argbPixels: IntArray,
        sampleWidth: Int,
        sampleHeight: Int,
    ): NearBlackInspection {
        require(sampleWidth > 0 && sampleHeight > 0) { "Sample dimensions must be positive" }
        require(sampleWidth.toLong() * sampleHeight.toLong() == argbPixels.size.toLong()) {
            "Pixel count must equal sampleWidth * sampleHeight"
        }

        val lumas = IntArray(argbPixels.size)
        var sum = 0L
        var sumOfSquares = 0L
        var extremelyDarkCount = 0
        var highlightCount = 0

        argbPixels.forEachIndexed { index, argb ->
            val luma = argbToLuma(argb)
            lumas[index] = luma
            sum += luma
            sumOfSquares += luma.toLong() * luma.toLong()
            if (luma <= thresholds.extremelyDarkLuma) extremelyDarkCount += 1
            if (luma >= thresholds.highlightLuma) highlightCount += 1
        }

        val count = argbPixels.size
        val mean = if (count == 0) 0.0 else sum.toDouble() / count
        val variance = if (count == 0) {
            0.0
        } else {
            (sumOfSquares.toDouble() / count - mean * mean).coerceAtLeast(0.0)
        }
        val edgeCount = countDetailEdges(lumas, sampleWidth, sampleHeight)
        val comparedEdgeCount =
            sampleHeight.toLong() * (sampleWidth - 1).toLong() +
                sampleWidth.toLong() * (sampleHeight - 1).toLong()
        val statistics = FrameLumaStatistics(
            sampleCount = count,
            meanLuma = mean,
            lumaStandardDeviation = sqrt(variance),
            extremelyDarkPixelRatio = ratio(extremelyDarkCount, count),
            highlightPixelRatio = ratio(highlightCount, count),
            detailEdgeRatio = if (comparedEdgeCount == 0L) {
                0.0
            } else {
                edgeCount.toDouble() / comparedEdgeCount
            },
        )
        return NearBlackInspection(classify(statistics), statistics)
    }

    fun classify(statistics: FrameLumaStatistics): NearBlackVerdict {
        if (statistics.sampleCount < thresholds.minimumSampleCount) {
            return NearBlackVerdict.INSUFFICIENT_DATA
        }
        val nearBlack =
            statistics.meanLuma <= thresholds.maximumMeanLuma &&
                statistics.lumaStandardDeviation <= thresholds.maximumLumaStandardDeviation &&
                statistics.extremelyDarkPixelRatio >=
                thresholds.minimumExtremelyDarkPixelRatio &&
                statistics.highlightPixelRatio <= thresholds.maximumHighlightPixelRatio &&
                statistics.detailEdgeRatio <= thresholds.maximumDetailEdgeRatio
        return if (nearBlack) NearBlackVerdict.NEAR_BLACK else NearBlackVerdict.USABLE
    }

    private fun countDetailEdges(lumas: IntArray, width: Int, height: Int): Long {
        var detailEdges = 0L
        for (y in 0 until height) {
            val rowStart = y * width
            for (x in 0 until width) {
                val index = rowStart + x
                if (
                    x + 1 < width &&
                    kotlin.math.abs(lumas[index] - lumas[index + 1]) >= thresholds.detailLumaDelta
                ) {
                    detailEdges += 1
                }
                if (
                    y + 1 < height &&
                    kotlin.math.abs(lumas[index] - lumas[index + width]) >=
                    thresholds.detailLumaDelta
                ) {
                    detailEdges += 1
                }
            }
        }
        return detailEdges
    }

    private fun ratio(numerator: Int, denominator: Int): Double =
        if (denominator == 0) 0.0 else numerator.toDouble() / denominator

    private fun argbToLuma(argb: Int): Int {
        val red = argb ushr 16 and 0xff
        val green = argb ushr 8 and 0xff
        val blue = argb and 0xff
        // Integer Rec.709 approximation; weights total 256.
        return (54 * red + 183 * green + 19 * blue + 128) ushr 8
    }
}

enum class NearBlackSignalState { CLEAR, SUSPECTED, CONFIRMED }

enum class NearBlackSignalEvent {
    NONE,
    SUSPECTED,
    CONFIRMED,
    RECOVERED,
}

data class NearBlackSignalUpdate(
    val state: NearBlackSignalState,
    val event: NearBlackSignalEvent,
    val consecutiveNearBlackFrames: Int,
)

/**
 * Requires consecutive near-black samples before emitting [NearBlackSignalEvent.CONFIRMED].
 *
 * A usable frame clears either a suspicion or a confirmed signal. Insufficient data neither
 * advances nor clears the sequence. This tracker only emits capture-health events: it does not
 * classify focus, end a session, or prescribe an upload policy.
 */
class NearBlackFrameTracker(
    private val confirmationsRequired: Int = 2,
) {
    private var consecutiveNearBlackFrames = 0
    private var state = NearBlackSignalState.CLEAR

    init {
        require(confirmationsRequired >= 2) { "At least two confirmations are required" }
    }

    @Synchronized
    fun observe(verdict: NearBlackVerdict): NearBlackSignalUpdate {
        val event = when (verdict) {
            NearBlackVerdict.INSUFFICIENT_DATA -> NearBlackSignalEvent.NONE
            NearBlackVerdict.USABLE -> {
                if (state == NearBlackSignalState.CLEAR) {
                    NearBlackSignalEvent.NONE
                } else {
                    consecutiveNearBlackFrames = 0
                    state = NearBlackSignalState.CLEAR
                    NearBlackSignalEvent.RECOVERED
                }
            }
            NearBlackVerdict.NEAR_BLACK -> {
                consecutiveNearBlackFrames += 1
                when {
                    state == NearBlackSignalState.CONFIRMED -> NearBlackSignalEvent.NONE
                    consecutiveNearBlackFrames >= confirmationsRequired -> {
                        state = NearBlackSignalState.CONFIRMED
                        NearBlackSignalEvent.CONFIRMED
                    }
                    else -> {
                        state = NearBlackSignalState.SUSPECTED
                        NearBlackSignalEvent.SUSPECTED
                    }
                }
            }
        }
        return NearBlackSignalUpdate(state, event, consecutiveNearBlackFrames)
    }

    @Synchronized
    fun reset(): NearBlackSignalUpdate {
        consecutiveNearBlackFrames = 0
        state = NearBlackSignalState.CLEAR
        return NearBlackSignalUpdate(state, NearBlackSignalEvent.NONE, 0)
    }
}

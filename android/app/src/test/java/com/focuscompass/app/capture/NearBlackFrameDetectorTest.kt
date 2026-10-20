package com.focuscompass.app.capture

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class NearBlackFrameDetectorTest {
    private val detector = NearBlackFrameDetector()

    @Test
    fun `uniform black frame is near black`() {
        val result = detector.inspectArgb(solidFrame(32, 32, 0), 32, 32)

        assertEquals(NearBlackVerdict.NEAR_BLACK, result.verdict)
        assertEquals(0.0, result.statistics.meanLuma, 0.0)
        assertEquals(1.0, result.statistics.extremelyDarkPixelRatio, 0.0)
    }

    @Test
    fun `minor near black sensor noise remains near black`() {
        val pixels = IntArray(32 * 32) { index -> gray(index % 5) }

        val result = detector.inspectArgb(pixels, 32, 32)

        assertEquals(NearBlackVerdict.NEAR_BLACK, result.verdict)
        assertTrue(result.statistics.meanLuma < 3.0)
    }

    @Test
    fun `dark interface with visible panels is usable`() {
        val pixels = solidFrame(32, 32, 2)
        for (y in 6 until 27) {
            for (x in 4 until 28) {
                pixels[y * 32 + x] = gray(18)
            }
        }

        assertEquals(
            NearBlackVerdict.USABLE,
            detector.inspectArgb(pixels, 32, 32).verdict,
        )
    }

    @Test
    fun `black background with visible white text is usable`() {
        val pixels = solidFrame(32, 32, 0)
        for (x in 7 until 25) {
            pixels[12 * 32 + x] = gray(255)
            pixels[18 * 32 + x] = gray(255)
        }
        for (y in 12..18) {
            pixels[y * 32 + 7] = gray(255)
            pixels[y * 32 + 24] = gray(255)
        }

        val result = detector.inspectArgb(pixels, 32, 32)

        assertEquals(NearBlackVerdict.USABLE, result.verdict)
        assertTrue(result.statistics.highlightPixelRatio > 0.001)
    }

    @Test
    fun `detailed dark video frame is usable`() {
        val pixels = IntArray(32 * 32) { index ->
            val x = index % 32
            val y = index / 32
            gray(2 + (x * 11 + y * 7) % 15)
        }

        assertEquals(
            NearBlackVerdict.USABLE,
            detector.inspectArgb(pixels, 32, 32).verdict,
        )
    }

    @Test
    fun `too small sample is not classified`() {
        assertEquals(
            NearBlackVerdict.INSUFFICIENT_DATA,
            detector.inspectArgb(solidFrame(8, 8, 0), 8, 8).verdict,
        )
    }

    @Test(expected = IllegalArgumentException::class)
    fun `pixel count must match sample dimensions`() {
        detector.inspectArgb(IntArray(10), 4, 4)
    }

    @Test
    fun `tracker requires two consecutive near black frames`() {
        val tracker = NearBlackFrameTracker()

        val first = tracker.observe(NearBlackVerdict.NEAR_BLACK)
        val second = tracker.observe(NearBlackVerdict.NEAR_BLACK)
        val third = tracker.observe(NearBlackVerdict.NEAR_BLACK)

        assertEquals(NearBlackSignalState.SUSPECTED, first.state)
        assertEquals(NearBlackSignalEvent.SUSPECTED, first.event)
        assertEquals(NearBlackSignalState.CONFIRMED, second.state)
        assertEquals(NearBlackSignalEvent.CONFIRMED, second.event)
        assertEquals(NearBlackSignalState.CONFIRMED, third.state)
        assertEquals(NearBlackSignalEvent.NONE, third.event)
    }

    @Test
    fun `usable frame clears suspicion before confirmation`() {
        val tracker = NearBlackFrameTracker()
        tracker.observe(NearBlackVerdict.NEAR_BLACK)

        val recovered = tracker.observe(NearBlackVerdict.USABLE)
        val nextDark = tracker.observe(NearBlackVerdict.NEAR_BLACK)

        assertEquals(NearBlackSignalEvent.RECOVERED, recovered.event)
        assertEquals(NearBlackSignalState.CLEAR, recovered.state)
        assertEquals(0, recovered.consecutiveNearBlackFrames)
        assertEquals(NearBlackSignalEvent.SUSPECTED, nextDark.event)
    }

    @Test
    fun `usable frame recovers a confirmed signal`() {
        val tracker = NearBlackFrameTracker()
        tracker.observe(NearBlackVerdict.NEAR_BLACK)
        tracker.observe(NearBlackVerdict.NEAR_BLACK)

        val recovered = tracker.observe(NearBlackVerdict.USABLE)

        assertEquals(NearBlackSignalState.CLEAR, recovered.state)
        assertEquals(NearBlackSignalEvent.RECOVERED, recovered.event)
    }

    @Test
    fun `insufficient sample neither confirms nor clears signal`() {
        val tracker = NearBlackFrameTracker()
        tracker.observe(NearBlackVerdict.NEAR_BLACK)

        val unknown = tracker.observe(NearBlackVerdict.INSUFFICIENT_DATA)
        val confirmed = tracker.observe(NearBlackVerdict.NEAR_BLACK)

        assertEquals(NearBlackSignalState.SUSPECTED, unknown.state)
        assertEquals(1, unknown.consecutiveNearBlackFrames)
        assertEquals(NearBlackSignalEvent.NONE, unknown.event)
        assertEquals(NearBlackSignalEvent.CONFIRMED, confirmed.event)
    }

    private fun solidFrame(width: Int, height: Int, luma: Int): IntArray =
        IntArray(width * height) { gray(luma) }

    private fun gray(value: Int): Int =
        (0xff shl 24) or (value shl 16) or (value shl 8) or value
}

package com.focuscompass.app.capture

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CapturePolicyTest {
    @Test
    fun `Android 14 and newer force whole display projection`() {
        assertFalse(shouldForceDefaultDisplayCapture(33))
        assertTrue(shouldForceDefaultDisplayCapture(34))
        assertTrue(shouldForceDefaultDisplayCapture(36))
    }

    @Test
    fun `scaleToFit preserves landscape aspect ratio`() {
        assertEquals(PixelSize(1_024, 576), scaleToFit(1_920, 1_080, 1_024))
    }

    @Test
    fun `scaleToFit preserves portrait aspect ratio`() {
        assertEquals(PixelSize(576, 1_024), scaleToFit(1_080, 1_920, 1_024))
    }

    @Test
    fun `scaleToFit does not upscale small images`() {
        assertEquals(PixelSize(800, 600), scaleToFit(800, 600, 1_024))
    }

    @Test
    fun `first frame is immediate and only one request can be in flight`() {
        val gate = FrameSamplingGate(20_000)
        assertTrue(gate.tryAcquire(1_000))
        assertFalse(gate.tryAcquire(21_000))
        gate.release()
        assertTrue(gate.tryAcquire(21_000))
    }

    @Test
    fun `sampling is not due before interval`() {
        val gate = FrameSamplingGate(20_000)
        assertTrue(gate.tryAcquire(0))
        gate.release()
        assertFalse(gate.tryAcquire(19_999))
        assertTrue(gate.tryAcquire(20_000))
    }

    @Test
    fun `missed sampling points are skipped instead of queued`() {
        val gate = FrameSamplingGate(20_000)
        assertTrue(gate.tryAcquire(0))
        gate.release()
        assertTrue(gate.tryAcquire(65_000))
        gate.release()
        assertFalse(gate.tryAcquire(65_001))
        assertTrue(gate.tryAcquire(80_000))
    }

    @Test
    fun `unsafe server policy is clamped`() {
        assertEquals(
            CapturePolicy(
                firstCaptureImmediate = false,
                intervalMillis = 5_000,
                requestTimeoutMillis = 4_000,
                maxImageDimension = 2_048,
                jpegQuality = 40,
            ),
            CapturePolicy.sanitized(
                firstCaptureImmediate = false,
                intervalMillis = 1,
                requestTimeoutMillis = 80_000,
                maxImageDimension = 9_999,
                jpegQuality = 1,
            ),
        )
    }

    @Test
    fun `backend may delay first frame by one interval`() {
        val gate = FrameSamplingGate(20_000, firstCaptureImmediate = false)
        assertFalse(gate.tryAcquire(1_000))
        assertFalse(gate.tryAcquire(20_999))
        assertTrue(gate.tryAcquire(21_000))
    }

    @Test
    fun `frame upload 404 is a lost session but transient failures skip one frame`() {
        assertEquals(FrameUploadFailureAction.SESSION_LOST, classifyFrameUploadFailure(404))
        assertEquals(FrameUploadFailureAction.SKIP_FRAME, classifyFrameUploadFailure(429))
        assertEquals(FrameUploadFailureAction.SKIP_FRAME, classifyFrameUploadFailure(500))
        assertEquals(FrameUploadFailureAction.SKIP_FRAME, classifyFrameUploadFailure(null))
    }

    @Test
    fun `frame upload authentication failures stop capture`() {
        assertEquals(FrameUploadFailureAction.AUTH_EXPIRED, classifyFrameUploadFailure(401))
        assertEquals(FrameUploadFailureAction.FORBIDDEN, classifyFrameUploadFailure(403))
    }
}

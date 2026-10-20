package com.focuscompass.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ProjectionHandshakeTest {
    @Test
    fun `authorized start survives until it is consumed exactly once`() {
        val handshake = SingleUseProjectionHandshake<Int>()
        val request = PendingStart(1.toString(), 25, 2.toString())
        handshake.prepare(request)

        assertEquals(request, handshake.pending())
        assertTrue(handshake.store(3, 4))
        val ready = handshake.take()

        assertEquals(request, ready?.request)
        assertEquals(3, ready?.consent?.resultCode)
        assertEquals(4, ready?.consent?.data)
        assertNull(handshake.take())
        assertNull(handshake.pending())
        assertFalse(handshake.hasConsent())
    }

    @Test
    fun `new request and cancellation discard an unused consent`() {
        val handshake = SingleUseProjectionHandshake<Int>()
        handshake.prepare(PendingStart(1.toString(), 25, 2.toString()))
        assertTrue(handshake.store(3, 4))

        val replacement = PendingStart(5.toString(), 30, 6.toString())
        handshake.prepare(replacement)
        assertFalse(handshake.hasConsent())
        assertNull(handshake.take())
        assertEquals(replacement, handshake.pending())

        handshake.cancel()
        assertNull(handshake.pending())
        assertFalse(handshake.store(7, 8))
    }

    @Test
    fun `reauthorization preserves the existing session and is consumed exactly once`() {
        val handshake = SingleUseReauthorizationHandshake<Int>()
        handshake.prepare("session-existing")

        assertEquals("session-existing", handshake.pendingSessionId())
        assertTrue(handshake.store(9, 10))

        val ready = handshake.take()
        assertEquals("session-existing", ready?.sessionId)
        assertEquals(9, ready?.consent?.resultCode)
        assertEquals(10, ready?.consent?.data)
        assertNull(handshake.take())
        assertNull(handshake.pendingSessionId())
    }

    @Test
    fun `replacement and cancellation discard unused reauthorization consent`() {
        val handshake = SingleUseReauthorizationHandshake<Int>()
        handshake.prepare("session-old")
        assertTrue(handshake.store(1, 2))

        handshake.prepare("session-current")
        assertNull(handshake.take())
        assertEquals("session-current", handshake.pendingSessionId())

        handshake.cancel()
        assertNull(handshake.pendingSessionId())
        assertFalse(handshake.store(3, 4))
    }

    @Test
    fun `reauthorization never revives an elapsed timestamped session`() {
        assertNull(
            selectReauthorizationRemainingSeconds(
                hasStartedAt = true,
                calculatedRemainingSeconds = 0,
                uiRemainingSeconds = 0,
                serverRemainingSeconds = 1_500,
            ),
        )
        assertEquals(
            42L,
            selectReauthorizationRemainingSeconds(
                hasStartedAt = true,
                calculatedRemainingSeconds = 42,
                uiRemainingSeconds = 0,
                serverRemainingSeconds = 1_500,
            ),
        )
    }

    @Test
    fun `session without timestamp can use positive recovery metadata`() {
        assertEquals(
            75L,
            selectReauthorizationRemainingSeconds(
                hasStartedAt = false,
                calculatedRemainingSeconds = 0,
                uiRemainingSeconds = 75,
                serverRemainingSeconds = 1_500,
            ),
        )
        assertEquals(
            1_500L,
            selectReauthorizationRemainingSeconds(
                hasStartedAt = false,
                calculatedRemainingSeconds = 0,
                uiRemainingSeconds = 0,
                serverRemainingSeconds = 1_500,
            ),
        )
    }
}

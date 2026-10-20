package com.focuscompass.app.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class SessionTimerTest {
    @Test
    fun calculatesRemainingSecondsFromServerStart() {
        assertEquals(
            1_200L,
            SessionTimer.remainingSeconds(
                startedAt = 1_787_875_200.0,
                durationMinutes = 25,
                nowEpochSeconds = 1_787_875_500L,
            ),
        )
    }

    @Test
    fun completedTimerNeverBecomesNegative() {
        assertEquals(
            0L,
            SessionTimer.remainingSeconds(
                startedAt = 1_787_875_200.0,
                durationMinutes = 5,
                nowEpochSeconds = 1_787_875_800L,
            ),
        )
    }

    @Test
    fun invalidServerTimeFailsClosed() {
        assertEquals(0L, SessionTimer.remainingSeconds(Double.NaN, 25, 0))
    }
}

package com.focuscompass.app.security

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TokenExpiryTest {
    @Test
    fun futureTokenIsValid() {
        assertFalse(TokenExpiry.isExpired("2026-09-27T00:00:00Z", 1_787_875_200L))
    }

    @Test
    fun tokenExpiringNowIsExpired() {
        assertTrue(TokenExpiry.isExpired("2026-08-28T00:00:00Z", 1_787_875_200L))
    }

    @Test
    fun malformedOrMissingExpiryFailsClosed() {
        assertTrue(TokenExpiry.isExpired("not-a-time", 0))
        assertTrue(TokenExpiry.isExpired(null, 0))
    }

    @Test
    fun unauthorizedAndTokenExpiredRequireLocalLogout() {
        assertTrue(AuthenticationFailure.requiresLogout(401))
        assertTrue(AuthenticationFailure.requiresLogout(400, "token_expired"))
        assertFalse(AuthenticationFailure.requiresLogout(403, "forbidden"))
    }
}

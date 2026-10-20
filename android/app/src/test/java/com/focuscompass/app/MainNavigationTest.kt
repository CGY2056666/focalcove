package com.focuscompass.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MainNavigationTest {
    @Test
    fun `bottom navigation is only visible on authenticated top level routes`() {
        listOf("home", "den", "history", "settings").forEach { route ->
            assertTrue(shouldShowBottomNavigation(route, authenticated = true))
        }

        listOf(
            null,
            "privacy",
            "auth",
            "focus",
            "report",
            "guide",
            HISTORY_DETAIL_ROUTE_PATTERN,
        ).forEach { route ->
            assertFalse(shouldShowBottomNavigation(route, authenticated = true))
        }
        assertFalse(shouldShowBottomNavigation("home", authenticated = false))
    }

    @Test
    fun `selected destination follows the current route`() {
        assertEquals(MainDestination.HOME, selectedMainDestination("home"))
        assertEquals(MainDestination.DEN, selectedMainDestination("den"))
        assertEquals(MainDestination.HISTORY, selectedMainDestination("history"))
        assertEquals(MainDestination.SETTINGS, selectedMainDestination("settings"))
        assertNull(selectedMainDestination("focus"))
        assertNull(selectedMainDestination(null))
    }

    @Test
    fun `history detail route contains the session id and hides bottom navigation`() {
        val route = historyDetailRoute("abc123")

        assertEquals("history-detail/abc123", route)
        assertFalse(shouldShowBottomNavigation(route, authenticated = true))
        assertNull(selectedMainDestination(route))
    }
}

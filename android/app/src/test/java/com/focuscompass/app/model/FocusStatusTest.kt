package com.focuscompass.app.model

import org.junit.Assert.assertEquals
import org.junit.Test

class FocusStatusTest {
    @Test
    fun mapsAllFourDisplayStates() {
        assertEquals(FocusDisplayStatus.FOCUSED, mapFocusStatus("focused"))
        assertEquals(FocusDisplayStatus.DISTRACTED, mapFocusStatus("off_task"))
        assertEquals(FocusDisplayStatus.PENDING_REVIEW, mapFocusStatus("pending_review"))
        assertEquals(FocusDisplayStatus.UNCERTAIN, mapFocusStatus("uncertain"))
    }

    @Test
    fun unknownAndMissingValuesAreUncertain() {
        assertEquals(FocusDisplayStatus.UNCERTAIN, mapFocusStatus(null))
        assertEquals(FocusDisplayStatus.UNCERTAIN, mapFocusStatus("new_server_state"))
    }
}

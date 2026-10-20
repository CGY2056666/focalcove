package com.focuscompass.app.ui.screens

import com.focuscompass.app.model.FocusDisplayStatus
import com.focuscompass.app.ui.theme.FocusStatusColors
import org.junit.Assert.assertEquals
import org.junit.Test

class StatusColorTest {
    @Test
    fun `each focus state uses the warm web palette`() {
        assertEquals(FocusStatusColors.Focused, statusColor(FocusDisplayStatus.FOCUSED))
        assertEquals(FocusStatusColors.Distracted, statusColor(FocusDisplayStatus.DISTRACTED))
        assertEquals(FocusStatusColors.Uncertain, statusColor(FocusDisplayStatus.UNCERTAIN))
        assertEquals(
            FocusStatusColors.PendingReview,
            statusColor(FocusDisplayStatus.PENDING_REVIEW),
        )
    }
}

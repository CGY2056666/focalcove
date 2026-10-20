package com.focuscompass.app.capture

import org.junit.Assert.assertTrue
import org.junit.Test

class CaptureNotificationsTest {
    @Test
    fun `notification id ranges do not overlap`() {
        val alertMin = CaptureNotifications.ALERT_NOTIFICATION_BASE_ID
        val alertMax = alertMin + CaptureNotifications.ALERT_NOTIFICATION_ID_MASK
        val warning = CaptureNotifications.CAPTURE_WARNING_NOTIFICATION_ID

        assertTrue(warning > alertMax)
        assertTrue(CaptureNotifications.ONGOING_NOTIFICATION_ID < alertMin)
    }
}

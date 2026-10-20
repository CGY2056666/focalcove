package com.focuscompass.app.model

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ReportReliabilityTest {
    @Test
    fun lowCoverageIsReferenceOnlyEvenWhenReliableFlagIsTrue() {
        val report = FocusReport(effectiveCoverage = 0.69, reliable = true)
        assertTrue(ReportReliability.isReferenceOnly(report))
    }

    @Test
    fun explicitUnreliableFlagIsReferenceOnly() {
        val report = FocusReport(effectiveCoverage = 0.95, reliable = false)
        assertTrue(ReportReliability.isReferenceOnly(report))
    }

    @Test
    fun sufficientCoverageAndNoFailureIsNormalReport() {
        val report = FocusReport(effectiveCoverage = 0.70, reliable = true)
        assertFalse(ReportReliability.isReferenceOnly(report))
    }

    @Test
    fun missingReportNeverLooksLikeAConfirmedScore() {
        assertTrue(ReportReliability.isReferenceOnly(null))
    }
}

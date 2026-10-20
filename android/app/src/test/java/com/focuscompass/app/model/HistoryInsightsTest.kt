package com.focuscompass.app.model

import java.time.LocalDate
import java.time.ZoneOffset
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class HistoryInsightsTest {
    @Test
    fun overviewOnlyAveragesReliableScoredRecords() {
        val history = listOf(
            HistoryItem(
                sessionId = "reliable-1",
                focusScore = 80.0,
                effectiveCoverage = 0.9,
                reliable = true,
            ),
            HistoryItem(
                sessionId = "reference",
                focusScore = 20.0,
                effectiveCoverage = 0.5,
                reliable = false,
            ),
            HistoryItem(
                sessionId = "reliable-2",
                focusScore = 100.0,
                effectiveCoverage = 0.70,
                reliable = true,
            ),
            HistoryItem(
                sessionId = "missing-score",
                focusScore = null,
                effectiveCoverage = 1.0,
                reliable = true,
            ),
            HistoryItem(
                sessionId = "missing-reliability",
                focusScore = 99.0,
                effectiveCoverage = 1.0,
                reliable = null,
            ),
        )

        val overview = buildHistoryOverview(history)

        assertEquals(5, overview.totalSessions)
        assertEquals(2, overview.reliableScoredSessions)
        assertEquals(90.0, overview.averageFocusScore ?: 0.0, 0.0)
    }

    @Test
    fun historyItemMapsToTheExistingReportReliabilityContract() {
        val item = HistoryItem(
            sessionId = "detail",
            focusScore = 65.5,
            pointsEarned = 3,
            focusedSeconds = 120.5,
            distractedSeconds = 15.25,
            effectiveCoverage = 0.45,
            reliable = false,
            summary = "有效画面不足",
        )

        val completion = item.toCompletionPayload()

        assertEquals("detail", completion.sessionId)
        assertEquals(3, completion.pointsEarned)
        assertEquals(120.5, completion.report?.focusedSeconds ?: 0.0, 0.0)
        assertEquals(15.25, completion.report?.distractedSeconds ?: 0.0, 0.0)
        assertEquals("有效画面不足", completion.report?.summary)
        assertTrue(ReportReliability.isReferenceOnly(completion.report))
    }

    @Test
    fun historyLookupUsesExactSessionId() {
        val item = HistoryItem(sessionId = "wanted")
        val history = listOf(HistoryItem(sessionId = "other"), item)

        assertEquals(item, findHistoryItem(history, "wanted"))
        assertNull(findHistoryItem(history, "missing"))
        assertNull(findHistoryItem(history, null))
    }

    @Test
    fun analyticsBuildsRecentCompletionCountsAndLabelsPlannedMinutesSeparately() {
        val today = LocalDate.of(2026, 8, 29)
        val history = listOf(
            HistoryItem(
                sessionId = "today-1",
                completedAt = today.epochSeconds(),
                durationMinutes = 25,
            ),
            HistoryItem(
                sessionId = "today-2",
                completedAt = today.epochSeconds() + 60,
                durationMinutes = 30,
            ),
            HistoryItem(
                sessionId = "six-days",
                completedAt = today.minusDays(6).epochSeconds(),
                durationMinutes = -5,
            ),
            HistoryItem(
                sessionId = "outside-window",
                completedAt = today.minusDays(7).epochSeconds(),
                durationMinutes = 60,
            ),
        )

        val analytics = buildHistoryAnalytics(history, today, ZoneOffset.UTC)

        assertEquals(115L, analytics.totalPlannedMinutes)
        assertEquals(
            listOf(1, 0, 0, 0, 0, 0, 2),
            analytics.dailyCompletions.map(DailyCompletion::count),
        )
    }

    @Test
    fun analyticsExcludesReferenceRecordsFromScoresAndJudgedDurations() {
        val today = LocalDate.of(2026, 8, 29)
        val base = today.epochSeconds()
        val history = listOf(
            HistoryItem(
                sessionId = "valid",
                completedAt = base,
                focusScore = 80.0,
                focusedSeconds = 120.0,
                distractedSeconds = 30.0,
                effectiveCoverage = 0.8,
                reliable = true,
            ),
            HistoryItem(
                sessionId = "low-coverage",
                completedAt = base + 1,
                focusScore = 95.0,
                focusedSeconds = 900.0,
                distractedSeconds = 100.0,
                effectiveCoverage = 0.5,
                reliable = true,
            ),
            HistoryItem(
                sessionId = "server-unreliable",
                completedAt = base + 2,
                focusScore = 90.0,
                focusedSeconds = 800.0,
                distractedSeconds = 200.0,
                effectiveCoverage = 0.9,
                reliable = false,
            ),
            HistoryItem(
                sessionId = "missing-reliability",
                completedAt = base + 3,
                focusScore = 88.0,
                focusedSeconds = 700.0,
                distractedSeconds = 300.0,
                effectiveCoverage = 0.9,
                reliable = null,
            ),
            HistoryItem(
                sessionId = "invalid-values",
                completedAt = base + 4,
                focusScore = Double.NaN,
                focusedSeconds = Double.POSITIVE_INFINITY,
                distractedSeconds = -1.0,
                effectiveCoverage = 0.9,
                reliable = true,
            ),
        )

        val analytics = buildHistoryAnalytics(history, today, ZoneOffset.UTC)

        assertEquals(listOf("valid"), analytics.reliableScoreTrend.map { it.sessionId })
        assertEquals(120.0, analytics.focusedSeconds, 0.0)
        assertEquals(30.0, analytics.distractedSeconds, 0.0)
        assertEquals(1, analytics.evidenceSessionCount)
    }

    @Test
    fun analyticsSortsTrendsOldestFirstLimitsThemAndClampsCoverage() {
        val today = LocalDate.of(2026, 8, 29)
        val base = today.epochSeconds()
        val scoreItems = (1..12).map { index ->
            HistoryItem(
                sessionId = "score-$index",
                completedAt = base + index,
                focusScore = index.toDouble(),
                effectiveCoverage = 0.9,
                reliable = true,
            )
        }.reversed()
        val coverageItems = listOf(
            HistoryItem(sessionId = "coverage-low", completedAt = base + 20, coverageRatio = -0.2),
            HistoryItem(sessionId = "coverage-high", completedAt = base + 21, coverageRatio = 1.5),
            HistoryItem(sessionId = "coverage-invalid", completedAt = base + 22, coverageRatio = Double.NaN),
        )

        val analytics = buildHistoryAnalytics(
            history = scoreItems + coverageItems,
            today = today,
            zoneId = ZoneOffset.UTC,
            trendLimit = 10,
        )

        assertEquals((3..12).map { "score-$it" }, analytics.reliableScoreTrend.map { it.sessionId })
        assertEquals(
            listOf(0.0, 1.0),
            analytics.coverageTrend.takeLast(2).map { it.coverage },
        )
    }

    private fun LocalDate.epochSeconds(): Double =
        atStartOfDay(ZoneOffset.UTC).toEpochSecond().toDouble()
}

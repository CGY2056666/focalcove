package com.focuscompass.app.model

import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

data class HistoryOverview(
    val totalSessions: Int,
    val reliableScoredSessions: Int,
    val averageFocusScore: Double?,
)

data class DailyCompletion(
    val date: LocalDate,
    val count: Int,
)

data class ReliableScorePoint(
    val sessionId: String,
    val completedAt: Double,
    val score: Double,
)

data class CoveragePoint(
    val sessionId: String,
    val completedAt: Double,
    val coverage: Double,
)

data class HistoryAnalytics(
    val totalPlannedMinutes: Long,
    val dailyCompletions: List<DailyCompletion>,
    val reliableScoreTrend: List<ReliableScorePoint>,
    val coverageTrend: List<CoveragePoint>,
    val focusedSeconds: Double,
    val distractedSeconds: Double,
    val evidenceSessionCount: Int,
)

fun buildHistoryOverview(history: List<HistoryItem>): HistoryOverview {
    val reliableScores = history
        .asSequence()
        .filter { it.reliable == true && !ReportReliability.isReferenceOnly(it) }
        .mapNotNull(HistoryItem::focusScore)
        .filter(Double::isFinite)
        .toList()
    return HistoryOverview(
        totalSessions = history.size,
        reliableScoredSessions = reliableScores.size,
        averageFocusScore = reliableScores.takeIf { it.isNotEmpty() }?.average(),
    )
}

fun buildHistoryAnalytics(
    history: List<HistoryItem>,
    today: LocalDate = LocalDate.now(),
    zoneId: ZoneId = ZoneId.systemDefault(),
    dayCount: Int = 7,
    trendLimit: Int = 10,
): HistoryAnalytics {
    require(dayCount > 0) { "dayCount must be positive" }
    require(trendLimit > 0) { "trendLimit must be positive" }

    val days = (dayCount - 1 downTo 0).map { offset ->
        today.minusDays(offset.toLong())
    }
    val completionCounts = days.associateWith { 0 }.toMutableMap()
    history.forEach { item ->
        item.historyTimestamp()?.toLocalDateOrNull(zoneId)?.let { date ->
            if (date in completionCounts) {
                completionCounts[date] = completionCounts.getValue(date) + 1
            }
        }
    }

    val reliableScoreTrend = history
        .asSequence()
        .filter { it.reliable == true && !ReportReliability.isReferenceOnly(it) }
        .mapNotNull { item ->
            val score = item.focusScore?.takeIf(Double::isFinite) ?: return@mapNotNull null
            val timestamp = item.historyTimestamp()?.takeIf(Double::isFinite) ?: return@mapNotNull null
            ReliableScorePoint(item.sessionId, timestamp, score)
        }
        .sortedWith(compareBy<ReliableScorePoint> { it.completedAt }.thenBy { it.sessionId })
        .toList()
        .takeLast(trendLimit)

    val coverageTrend = history
        .asSequence()
        .mapNotNull { item ->
            val coverage = (item.effectiveCoverage ?: item.coverageRatio)
                ?.takeIf(Double::isFinite)
                ?: return@mapNotNull null
            val timestamp = item.historyTimestamp()?.takeIf(Double::isFinite) ?: return@mapNotNull null
            CoveragePoint(item.sessionId, timestamp, coverage.coerceIn(0.0, 1.0))
        }
        .sortedWith(compareBy<CoveragePoint> { it.completedAt }.thenBy { it.sessionId })
        .toList()
        .takeLast(trendLimit)

    var evidenceSessionCount = 0
    val focusedDurations = mutableListOf<Double>()
    val distractedDurations = mutableListOf<Double>()
    history.forEach { item ->
        if (item.reliable != true || ReportReliability.isReferenceOnly(item)) return@forEach
        val focused = item.focusedSeconds.validDurationOrNull()
        val distracted = item.distractedSeconds.validDurationOrNull()
        if (focused != null || distracted != null) {
            evidenceSessionCount += 1
            focusedDurations += focused ?: 0.0
            distractedDurations += distracted ?: 0.0
        }
    }

    return HistoryAnalytics(
        totalPlannedMinutes = history.sumOf { item ->
            item.durationMinutes?.takeIf { it > 0 }?.toLong() ?: 0L
        },
        dailyCompletions = days.map { date ->
            DailyCompletion(date, completionCounts.getValue(date))
        },
        reliableScoreTrend = reliableScoreTrend,
        coverageTrend = coverageTrend,
        focusedSeconds = focusedDurations.sum().takeIf { it.isFinite() } ?: 0.0,
        distractedSeconds = distractedDurations.sum().takeIf { it.isFinite() } ?: 0.0,
        evidenceSessionCount = evidenceSessionCount,
    )
}

fun findHistoryItem(history: List<HistoryItem>, sessionId: String?): HistoryItem? =
    sessionId?.let { id -> history.firstOrNull { it.sessionId == id } }

fun HistoryItem.toCompletionPayload(): CompletionPayload = CompletionPayload(
    sessionId = sessionId,
    pointsEarned = pointsEarned ?: 0,
    report = FocusReport(
        focusScore = focusScore,
        focusedSeconds = focusedSeconds,
        distractedSeconds = distractedSeconds,
        effectiveCoverage = effectiveCoverage,
        coverageRatio = coverageRatio,
        reliable = reliable,
        summary = summary,
    ),
)

private fun HistoryItem.historyTimestamp(): Double? = completedAt ?: startedAt

private fun Double?.validDurationOrNull(): Double? =
    this?.takeIf { it.isFinite() && it >= 0.0 }

private fun Double.toLocalDateOrNull(zoneId: ZoneId): LocalDate? = runCatching {
    Instant.ofEpochSecond(toLong()).atZone(zoneId).toLocalDate()
}.getOrNull()

package com.focuscompass.app.model

import com.google.gson.annotations.SerializedName

data class AuthRequest(val username: String, val password: String)

data class AuthPayload(
    @SerializedName("access_token") val token: String,
    val username: String,
    @SerializedName("expires_at") val expiresAt: String,
)

data class CapturePolicy(
    @SerializedName("first_immediate") val initialCaptureImmediately: Boolean = true,
    @SerializedName("interval_seconds") val intervalSeconds: Int = 20,
    @SerializedName("max_edge_pixels") val maxLongEdgePx: Int = 1024,
    @SerializedName("jpeg_quality") val jpegQuality: Int = 72,
    @SerializedName("request_timeout_seconds") val requestTimeoutSeconds: Int = 18,
)

data class BootstrapPayload(
    val username: String? = null,
    val points: Int = 0,
    @SerializedName("suggested_duration_minutes") val recommendedDurationMinutes: Int? = null,
    @SerializedName("recent_history") val recentHistory: List<HistoryItem> = emptyList(),
    @SerializedName("capture_policy") val capturePolicy: CapturePolicy = CapturePolicy(),
)

data class StartFocusRequest(
    val goal: String,
    @SerializedName("duration_minutes") val durationMinutes: Int,
    @SerializedName("monitoring_mode") val reminderMode: String,
)

data class CompleteRequest(val reason: String)

data class FrameSummary(
    @SerializedName("frame_id") val frameId: String? = null,
    val status: String? = null,
    val score: Double? = null,
    val explanation: String? = null,
    @SerializedName("captured_at") val capturedAt: Double? = null,
)

data class AlertEvent(
    @SerializedName("event_id") val eventId: String,
    val title: String? = null,
    val message: String? = null,
    val status: String? = null,
)

data class FocusSessionPayload(
    @SerializedName("session_id") val sessionId: String,
    val goal: String? = null,
    @SerializedName("duration_minutes") val durationMinutes: Int? = null,
    @SerializedName("started_at") val startedAt: Double? = null,
    @SerializedName("remaining_seconds") val remainingSeconds: Long? = null,
    val status: String? = null,
    @SerializedName("latest_frame") val latestFrame: FrameSummary? = null,
    @SerializedName("rolling_summary") val rollingSummary: String? = null,
    @SerializedName("alert_event") val alertEvent: AlertEvent? = null,
    @SerializedName("capture_policy") val capturePolicy: CapturePolicy? = null,
)

data class FocusReport(
    @SerializedName("focus_score") val focusScore: Double? = null,
    @SerializedName("focused_seconds") val focusedSeconds: Double? = null,
    @SerializedName("distracted_seconds") val distractedSeconds: Double? = null,
    @SerializedName("effective_coverage") val effectiveCoverage: Double? = null,
    @SerializedName("coverage_ratio") val coverageRatio: Double? = null,
    val reliable: Boolean? = null,
    val summary: String? = null,
)

data class CompletionPayload(
    @SerializedName("session_id") val sessionId: String,
    @SerializedName("already_completed") val alreadyCompleted: Boolean = false,
    @SerializedName("points_earned") val pointsEarned: Int = 0,
    val report: FocusReport? = null,
)

data class HistoryItem(
    @SerializedName("session_id") val sessionId: String,
    val goal: String? = null,
    @SerializedName("started_at") val startedAt: Double? = null,
    @SerializedName(value = "completed_at", alternate = ["ended_at"]) val completedAt: Double? = null,
    @SerializedName("duration_minutes") val durationMinutes: Int? = null,
    @SerializedName("focus_score") val focusScore: Double? = null,
    @SerializedName("points_earned") val pointsEarned: Int? = null,
    @SerializedName("focused_seconds") val focusedSeconds: Double? = null,
    @SerializedName("distracted_seconds") val distractedSeconds: Double? = null,
    @SerializedName("effective_coverage") val effectiveCoverage: Double? = null,
    @SerializedName("coverage_ratio") val coverageRatio: Double? = null,
    val reliable: Boolean? = null,
    val summary: String? = null,
)

data class HistoryPayload(val items: List<HistoryItem> = emptyList())

data class DenConfig(
    val floor: String = "base_floor",
    val wall: String = "base_wall",
    val decoration: List<String> = emptyList(),
    val ambience: String = "day",
)

data class DenItem(
    val id: String,
    val name: String,
    val price: Int,
    val description: String,
    @SerializedName("scene_group") val sceneGroup: String,
    @SerializedName("scene_slot") val sceneSlot: String,
    val owned: Boolean = false,
)

data class DenPayload(
    val points: Int = 0,
    val items: List<DenItem> = emptyList(),
    val config: DenConfig = DenConfig(),
)

data class DenUpdateRequest(
    @SerializedName("den_config") val denConfig: DenConfig,
)

data class ExchangeRequest(
    @SerializedName("item_id") val itemId: String,
)

fun updateDenConfig(config: DenConfig, item: DenItem): DenConfig {
    if (!item.owned) return config
    return when (item.sceneGroup) {
        "floor" -> config.copy(floor = item.id)
        "wall" -> config.copy(wall = item.id)
        "decoration" -> {
            val decoration = if (item.id in config.decoration) {
                config.decoration - item.id
            } else {
                config.decoration + item.id
            }
            config.copy(decoration = decoration)
        }
        else -> config
    }
}

fun updateDenAmbience(config: DenConfig, ambience: String): DenConfig =
    config.copy(ambience = if (ambience == "night") "night" else "day")

fun isDenItemEquipped(config: DenConfig, item: DenItem): Boolean = when (item.sceneGroup) {
    "floor" -> config.floor == item.id
    "wall" -> config.wall == item.id
    "decoration" -> item.id in config.decoration
    else -> false
}

data class ApiErrorEnvelope(val error: ApiErrorBody)

data class ApiErrorBody(
    val code: String,
    val message: String,
    val retryable: Boolean = false,
)

enum class FocusDisplayStatus(val label: String) {
    FOCUSED("专注"),
    DISTRACTED("分心"),
    UNCERTAIN("不确定"),
    PENDING_REVIEW("待复核"),
}

fun mapFocusStatus(raw: String?): FocusDisplayStatus = when (raw?.trim()?.lowercase()) {
    "focused", "focus", "on_task", "productive" -> FocusDisplayStatus.FOCUSED
    "distracted", "distraction", "off_task" -> FocusDisplayStatus.DISTRACTED
    "pending_review", "pending", "review" -> FocusDisplayStatus.PENDING_REVIEW
    else -> FocusDisplayStatus.UNCERTAIN
}

object ReportReliability {
    const val MIN_EFFECTIVE_COVERAGE = 0.70

    fun isReferenceOnly(report: FocusReport?): Boolean {
        if (report == null) return true
        if (report.reliable == false) return true
        val coverage = report.effectiveCoverage ?: report.coverageRatio
        return coverage != null && coverage < MIN_EFFECTIVE_COVERAGE
    }

    fun isReferenceOnly(item: HistoryItem): Boolean {
        if (item.reliable == false) return true
        val coverage = item.effectiveCoverage ?: item.coverageRatio
        return coverage != null && coverage < MIN_EFFECTIVE_COVERAGE
    }
}

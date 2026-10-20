package com.focuscompass.app.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.focuscompass.app.model.CompletionPayload
import com.focuscompass.app.model.DailyCompletion
import com.focuscompass.app.model.FocusDisplayStatus
import com.focuscompass.app.model.FocusSessionPayload
import com.focuscompass.app.model.HistoryAnalytics
import com.focuscompass.app.model.HistoryItem
import com.focuscompass.app.model.ReportReliability
import com.focuscompass.app.model.buildHistoryAnalytics
import com.focuscompass.app.model.buildHistoryOverview
import com.focuscompass.app.model.mapFocusStatus
import com.focuscompass.app.model.toCompletionPayload
import com.focuscompass.app.capture.CaptureHealthWarning
import com.focuscompass.app.ui.theme.FocusStatusColors
import java.util.Locale

@Composable
fun FocusSessionScreen(
    session: FocusSessionPayload?,
    remainingSeconds: Long,
    liveStatus: String? = null,
    liveSummary: String? = null,
    monitoringInterrupted: Boolean = false,
    captureHealthWarning: CaptureHealthWarning? = null,
    reauthorizationAvailable: Boolean = false,
    isCompleting: Boolean = false,
    onRefresh: () -> Unit,
    onReauthorize: () -> Unit = {},
    onComplete: () -> Unit,
    onAbandon: () -> Unit,
) {
    val displayStatus = mapFocusStatus(liveStatus ?: session?.latestFrame?.status ?: session?.status)
    val stateColor = statusColor(displayStatus)
    WarmScreen {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 22.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(
                "专注进行中",
                color = MaterialTheme.colorScheme.primary,
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.Bold,
            )
            Text(
                session?.goal.orEmpty().ifBlank { "当前专注目标" },
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold,
            )
            if (captureHealthWarning != null) {
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.tertiaryContainer,
                    ),
                ) {
                    Column(
                        modifier = Modifier.padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        Text(
                            "投屏画面可能已失效",
                            color = MaterialTheme.colorScheme.onTertiaryContainer,
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                        )
                        Text(
                            captureHealthWarning.message,
                            color = MaterialTheme.colorScheme.onTertiaryContainer,
                        )
                        Text(
                            "这些画面已跳过，不会上传，也不会被记为分心。离开安全页面后可等待自动恢复，或重新授权整屏共享。",
                            color = MaterialTheme.colorScheme.onTertiaryContainer,
                            style = MaterialTheme.typography.bodySmall,
                        )
                        if (reauthorizationAvailable) {
                            Button(onClick = onReauthorize, modifier = Modifier.fillMaxWidth()) {
                                Text("重新授权整屏共享")
                            }
                        }
                    }
                }
            }
            if (monitoringInterrupted && captureHealthWarning == null) {
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer),
                ) {
                    Column(
                        modifier = Modifier.padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        Text(
                            "整屏监控已中断。本轮仍可直接结算，但中断后的时间没有画面证据。",
                            color = MaterialTheme.colorScheme.onErrorContainer,
                        )
                        if (reauthorizationAvailable) {
                            Button(onClick = onReauthorize, modifier = Modifier.fillMaxWidth()) {
                                Text("重新授权并继续本轮")
                            }
                        }
                    }
                }
            }
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primary),
            ) {
                Column(
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 28.dp).fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text(
                        "剩余时间",
                        color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.78f),
                        style = MaterialTheme.typography.labelLarge,
                    )
                    Text(
                        formatClock(remainingSeconds),
                        modifier = Modifier.fillMaxWidth(),
                        color = MaterialTheme.colorScheme.onPrimary,
                        style = MaterialTheme.typography.headlineLarge,
                        fontWeight = FontWeight.Bold,
                        maxLines = 1,
                        textAlign = TextAlign.Center,
                    )
                }
            }
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = stateColor.copy(alpha = 0.10f)),
            ) {
                Row(
                    modifier = Modifier.padding(18.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    verticalAlignment = Alignment.Top,
                ) {
                    Box(
                        modifier = Modifier
                            .padding(top = 5.dp)
                            .size(11.dp)
                            .clip(CircleShape)
                            .background(stateColor),
                    )
                    Column(
                        modifier = Modifier.weight(1f),
                        verticalArrangement = Arrangement.spacedBy(5.dp),
                    ) {
                        Text(
                            displayStatus.label,
                            color = stateColor,
                            style = MaterialTheme.typography.titleLarge,
                            fontWeight = FontWeight.Bold,
                        )
                        Text(
                            session?.latestFrame?.explanation?.takeIf { it.isNotBlank() }
                                ?: "首帧分析后，这里会显示当前画面判断。",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                }
            }
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
            ) {
                Column(
                    modifier = Modifier.padding(18.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text("本轮摘要", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text(
                        liveSummary ?: session?.rollingSummary ?: "首帧分析后，这里会显示滚动摘要。",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodyLarge,
                    )
                }
            }
            Text(
                "整屏共享期间系统会持续显示通知。安全页面的空白画面不会被判定为确定分心。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            OutlinedButton(onClick = onRefresh, modifier = Modifier.fillMaxWidth()) {
                Text("刷新状态")
            }
            Button(
                onClick = onComplete,
                enabled = !isCompleting,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(if (isCompleting) "正在结算…" else "结束并生成报告")
            }
            OutlinedButton(
                onClick = onAbandon,
                enabled = !isCompleting,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("放弃本轮（不生成报告）")
            }
            Spacer(Modifier.height(8.dp))
        }
    }
}

@Composable
fun ReportScreen(
    completion: CompletionPayload?,
    onHome: () -> Unit,
    eyebrow: String = "专注报告",
    headline: String = "本轮完成",
    meta: String? = null,
    actionLabel: String = "返回首页",
) {
    val report = completion?.report
    val referenceOnly = ReportReliability.isReferenceOnly(report)
    val coverage = report?.effectiveCoverage ?: report?.coverageRatio
    val scoreText = report?.focusScore?.let { String.format(Locale.getDefault(), "%.1f", it) } ?: "—"
    val coverageText = coverage?.let { String.format(Locale.getDefault(), "%.0f%%", it * 100) } ?: "—"

    WarmScreen {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 22.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        eyebrow,
                        color = MaterialTheme.colorScheme.primary,
                        style = MaterialTheme.typography.labelLarge,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(headline, style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
                    meta?.takeIf { it.isNotBlank() }?.let {
                        Text(
                            it,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                }
                Surface(
                    color = MaterialTheme.colorScheme.primaryContainer,
                    shape = RoundedCornerShape(999.dp),
                ) {
                    Text(
                        "+${completion?.pointsEarned ?: 0} 积分",
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                        color = MaterialTheme.colorScheme.onPrimaryContainer,
                        style = MaterialTheme.typography.labelLarge,
                        fontWeight = FontWeight.Bold,
                    )
                }
            }
            if (referenceOnly) {
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(
                        containerColor = FocusStatusColors.Uncertain.copy(alpha = 0.10f),
                    ),
                ) {
                    Column(
                        modifier = Modifier.padding(18.dp),
                        verticalArrangement = Arrangement.spacedBy(5.dp),
                    ) {
                        Text(
                            "仅供参考",
                            color = FocusStatusColors.Uncertain,
                            style = MaterialTheme.typography.titleLarge,
                            fontWeight = FontWeight.Bold,
                        )
                        Text("本轮有效画面覆盖不足或报告未通过可靠性检查，不按普通成绩展示。")
                    }
                }
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                ReportMetric("专注得分", scoreText, Modifier.weight(1f))
                ReportMetric("有效覆盖率", coverageText, Modifier.weight(1f))
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                ReportMetric("专注时长", formatReportDuration(report?.focusedSeconds), Modifier.weight(1f))
                ReportMetric("分心时长", formatReportDuration(report?.distractedSeconds), Modifier.weight(1f))
            }
            report?.summary?.takeIf { it.isNotBlank() }?.let {
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                ) {
                    Column(
                        modifier = Modifier.padding(18.dp),
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        Text("本轮总结", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                        Text(it, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyLarge)
                    }
                }
            }
            Button(onClick = onHome, modifier = Modifier.fillMaxWidth()) {
                Text(actionLabel)
            }
            Spacer(Modifier.height(8.dp))
        }
    }
}

@Composable
private fun ReportMetric(label: String, value: String, modifier: Modifier = Modifier) {
    Card(
        modifier = modifier,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    ) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.labelMedium)
            Text(value, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
fun HistoryScreen(
    history: List<HistoryItem>,
    onOpenHistoryItem: (HistoryItem) -> Unit,
) {
    val analytics = buildHistoryAnalytics(history)
    WarmScreen {
        Column(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Column(
                modifier = Modifier.padding(start = 20.dp, top = 22.dp, end = 20.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Text(
                    "专注记录",
                    color = MaterialTheme.colorScheme.primary,
                    style = MaterialTheme.typography.labelLarge,
                    fontWeight = FontWeight.Bold,
                )
                Text("最近记录与趋势", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
            }
            if (history.isEmpty()) {
                Box(
                    modifier = Modifier.fillMaxSize().padding(24.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
                        Column(
                            modifier = Modifier.padding(24.dp),
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            Text("还没有已完成的专注记录", style = MaterialTheme.typography.titleMedium)
                            Text(
                                "完成第一轮后，报告会保存在这里。",
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                    }
                }
            } else {
                LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(start = 20.dp, end = 20.dp, bottom = 24.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    item {
                        HistoryOverviewCard(history, analytics)
                    }
                    item {
                        CompletionRhythmCard(analytics.dailyCompletions)
                    }
                    item {
                        ReliableScoreTrendCard(analytics)
                    }
                    item {
                        EvidenceQualityCard(analytics)
                    }
                    item {
                        Text(
                            "记录明细",
                            modifier = Modifier.padding(top = 4.dp),
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                    items(history, key = { it.sessionId }) { item ->
                        HistoryCard(item, onClick = { onOpenHistoryItem(item) })
                    }
                }
            }
        }
    }
}

@Composable
private fun HistoryOverviewCard(history: List<HistoryItem>, analytics: HistoryAnalytics) {
    val overview = buildHistoryOverview(history)
    val averageScore = overview.averageFocusScore
        ?.let { String.format(Locale.getDefault(), "%.1f", it) }
        ?: "—"
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer),
    ) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                "当前加载数据概览",
                color = MaterialTheme.colorScheme.onPrimaryContainer,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OverviewMetric("记录", overview.totalSessions.toString(), Modifier.weight(1f))
                OverviewMetric(
                    "计划总时长",
                    formatPlannedMinutes(analytics.totalPlannedMinutes),
                    Modifier.weight(1f),
                )
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OverviewMetric("完整评分", overview.reliableScoredSessions.toString(), Modifier.weight(1f))
                OverviewMetric("可靠均分", averageScore, Modifier.weight(1f))
            }
            Text(
                "计划总时长不是实际专注时长；低覆盖率记录不会计入可靠均分。接口当前最多加载最近 50 条。",
                color = MaterialTheme.colorScheme.onPrimaryContainer,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun CompletionRhythmCard(days: List<DailyCompletion>) {
    val maxCount = days.maxOfOrNull(DailyCompletion::count)?.coerceAtLeast(1) ?: 1
    val total = days.sumOf(DailyCompletion::count)
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    ) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("近 7 天完成节奏", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text(
                "每日完成轮次",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalAlignment = Alignment.Bottom,
            ) {
                days.forEach { day ->
                    val barHeight = if (day.count == 0) {
                        3.dp
                    } else {
                        (10f + 58f * day.count.toFloat() / maxCount.toFloat()).dp
                    }
                    Column(
                        modifier = Modifier.weight(1f),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        Box(
                            modifier = Modifier.fillMaxWidth().height(70.dp),
                            contentAlignment = Alignment.BottomCenter,
                        ) {
                            Surface(
                                modifier = Modifier.width(18.dp).height(barHeight),
                                color = if (day.count > 0) {
                                    MaterialTheme.colorScheme.primary
                                } else {
                                    MaterialTheme.colorScheme.outlineVariant
                                },
                                shape = RoundedCornerShape(topStart = 8.dp, topEnd = 8.dp),
                            ) {}
                        }
                        Text(dayLabel(day), style = MaterialTheme.typography.labelSmall)
                        Text(
                            day.count.toString(),
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            style = MaterialTheme.typography.labelSmall,
                        )
                    }
                }
            }
            Text(
                "最近 7 天共完成 $total 轮；仅统计当前已加载的记录。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun ReliableScoreTrendCard(analytics: HistoryAnalytics) {
    val scores = analytics.reliableScoreTrend.map { it.score.coerceIn(0.0, 100.0) }
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    ) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("最近可靠评分", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            if (scores.isEmpty()) {
                Text(
                    "当前记录中还没有服务端标记为可靠的评分。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                MiniBarChart(
                    values = scores,
                    maxSlots = 10,
                    maxValue = 100.0,
                    colorForValue = { MaterialTheme.colorScheme.primary },
                )
                val average = scores.average()
                Text(
                    "最近 ${scores.size} 次均分 ${String.format(Locale.getDefault(), "%.1f", average)}，" +
                        "范围 ${String.format(Locale.getDefault(), "%.1f", scores.min())}–" +
                        "${String.format(Locale.getDefault(), "%.1f", scores.max())} 分。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
                Text(
                    "柱形从左到右由旧到新，只描述记录变化，不代表注意力改善或下降。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
    }
}

@Composable
private fun EvidenceQualityCard(analytics: HistoryAnalytics) {
    val coverageValues = analytics.coverageTrend.map { it.coverage }
    val judgedSeconds = analytics.focusedSeconds + analytics.distractedSeconds
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    ) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("画面证据质量", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            if (coverageValues.isEmpty()) {
                Text(
                    "当前记录中没有可用的有效覆盖率。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                MiniBarChart(
                    values = coverageValues,
                    maxSlots = 10,
                    maxValue = 1.0,
                    colorForValue = { coverage ->
                        if (coverage >= ReportReliability.MIN_EFFECTIVE_COVERAGE) {
                            FocusStatusColors.Focused
                        } else {
                            FocusStatusColors.Uncertain
                        }
                    },
                )
                val latestCoverage = coverageValues.last() * 100.0
                val belowThreshold = coverageValues.count {
                    it < ReportReliability.MIN_EFFECTIVE_COVERAGE
                }
                Text(
                    "最近 ${coverageValues.size} 条中，最新有效覆盖率 " +
                        "${String.format(Locale.getDefault(), "%.0f", latestCoverage)}%，" +
                        "$belowThreshold 条低于 70%。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
                Text(
                    "70% 仅是覆盖率参考线，最终仍以服务端“仅供参考”标记为准。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }

            HorizontalDivider()
            Text("可靠记录的明确判定时段", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
            if (judgedSeconds > 0.0 && judgedSeconds.isFinite()) {
                val focusedRatio = (analytics.focusedSeconds / judgedSeconds).coerceIn(0.0, 1.0)
                LinearProgressIndicator(
                    progress = { focusedRatio.toFloat() },
                    modifier = Modifier.fillMaxWidth().height(12.dp).clip(RoundedCornerShape(999.dp)),
                    color = FocusStatusColors.Focused,
                    trackColor = FocusStatusColors.Distracted,
                )
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Text(
                        "相关 ${formatReportDuration(analytics.focusedSeconds)}",
                        color = FocusStatusColors.Focused,
                        style = MaterialTheme.typography.bodySmall,
                    )
                    Text(
                        "偏离 ${formatReportDuration(analytics.distractedSeconds)}",
                        color = FocusStatusColors.Distracted,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            } else {
                Text(
                    "当前没有可靠记录可用于汇总明确判定时段。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                "仅汇总 ${analytics.evidenceSessionCount} 条服务端标记可靠记录中的模型估算片段，" +
                    "不代表整轮实际专注率。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun MiniBarChart(
    values: List<Double>,
    maxSlots: Int,
    maxValue: Double,
    colorForValue: @Composable (Double) -> Color,
) {
    val displayedValues = values.takeLast(maxSlots)
    Row(
        modifier = Modifier.fillMaxWidth().height(88.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalAlignment = Alignment.Bottom,
    ) {
        repeat((maxSlots - displayedValues.size).coerceAtLeast(0)) {
            Spacer(Modifier.weight(1f))
        }
        displayedValues.forEach { value ->
            val ratio = (value / maxValue).coerceIn(0.0, 1.0)
            Surface(
                modifier = Modifier
                    .weight(1f)
                    .height((6f + ratio.toFloat() * 76f).dp),
                color = colorForValue(value),
                shape = RoundedCornerShape(topStart = 8.dp, topEnd = 8.dp),
            ) {}
        }
    }
}

@Composable
private fun OverviewMetric(label: String, value: String, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(3.dp),
    ) {
        Text(
            value,
            color = MaterialTheme.colorScheme.onPrimaryContainer,
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.Bold,
        )
        Text(
            label,
            color = MaterialTheme.colorScheme.onPrimaryContainer,
            style = MaterialTheme.typography.labelSmall,
        )
    }
}

@Composable
private fun HistoryCard(item: HistoryItem, onClick: () -> Unit) {
    val referenceOnly = ReportReliability.isReferenceOnly(item)
    val badgeColor = if (referenceOnly) FocusStatusColors.Uncertain else FocusStatusColors.Focused
    Card(
        onClick = onClick,
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(9.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top,
            ) {
                Text(
                    item.goal ?: "未命名目标",
                    modifier = Modifier.weight(1f),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                )
                Surface(
                    color = badgeColor.copy(alpha = 0.10f),
                    shape = RoundedCornerShape(999.dp),
                ) {
                    Text(
                        if (referenceOnly) "仅供参考" else "记录完整",
                        modifier = Modifier.padding(horizontal = 9.dp, vertical = 5.dp),
                        color = badgeColor,
                        style = MaterialTheme.typography.labelSmall,
                        fontWeight = FontWeight.Bold,
                    )
                }
            }
            Text(
                (item.completedAt ?: item.startedAt)?.let(::formatEpochTime) ?: "时间未知",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            HorizontalDivider()
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    "${if (referenceOnly) "参考分" else "得分"}：${item.focusScore?.let { String.format(Locale.getDefault(), "%.1f", it) } ?: "—"}",
                    modifier = Modifier.weight(1f),
                )
                Text(
                    "积分：${item.pointsEarned ?: 0}",
                    modifier = Modifier.weight(1f),
                    textAlign = TextAlign.End,
                )
            }
            Text(
                "查看完整报告",
                modifier = Modifier.fillMaxWidth(),
                color = MaterialTheme.colorScheme.primary,
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.Bold,
                textAlign = TextAlign.End,
            )
        }
    }
}

@Composable
fun HistoryDetailScreen(
    item: HistoryItem?,
    loading: Boolean,
    onBack: () -> Unit,
) {
    if (item == null) {
        WarmScreen {
            Column(
                modifier = Modifier.fillMaxSize().padding(horizontal = 20.dp, vertical = 22.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                Text(
                    "历史报告",
                    color = MaterialTheme.colorScheme.primary,
                    style = MaterialTheme.typography.labelLarge,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    if (loading) "正在加载记录…" else "暂时无法显示这条记录",
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold,
                )
                if (!loading) {
                    Text(
                        "请返回记录页后重试。",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                OutlinedButton(onClick = onBack, modifier = Modifier.fillMaxWidth()) {
                    Text("返回记录")
                }
            }
        }
        return
    }

    val completedText = (item.completedAt ?: item.startedAt)
        ?.let(::formatEpochTime)
        ?: "时间未知"
    val planText = item.durationMinutes
        ?.takeIf { it > 0 }
        ?.let { " · 计划 $it 分钟" }
        .orEmpty()
    ReportScreen(
        completion = item.toCompletionPayload(),
        onHome = onBack,
        eyebrow = "历史报告",
        headline = item.goal?.takeIf { it.isNotBlank() } ?: "未命名目标",
        meta = completedText + planText,
        actionLabel = "返回记录",
    )
}

@Composable
fun SettingsScreen(
    username: String?,
    points: Int,
    baseUrl: String,
    appVersion: String,
    serverConfigured: Boolean,
    soundEnabled: Boolean,
    onSoundChanged: (Boolean) -> Unit,
    onOpenGuide: () -> Unit,
    onLogout: () -> Unit,
) {
    WarmScreen {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 22.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            BrandLockup(subtitle = "账号与应用设置")
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
            ) {
                Row(
                    modifier = Modifier.padding(18.dp).fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("当前账号", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.labelMedium)
                        Text(username ?: "未获取用户名", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                    }
                    Surface(
                        color = MaterialTheme.colorScheme.primaryContainer,
                        shape = RoundedCornerShape(999.dp),
                    ) {
                        Text(
                            "$points 积分",
                            modifier = Modifier.padding(horizontal = 11.dp, vertical = 7.dp),
                            color = MaterialTheme.colorScheme.onPrimaryContainer,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }
            }
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
            ) {
                Row(
                    modifier = Modifier.padding(18.dp).fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("提醒声音", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                        Text(
                            "关闭后仍保留通知文字",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                    Switch(checked = soundEnabled, onCheckedChange = onSoundChanged)
                }
            }
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
            ) {
                Column(
                    modifier = Modifier.padding(18.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text("服务器", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text(baseUrl, style = MaterialTheme.typography.bodyMedium)
                    if (!serverConfigured) {
                        Text(
                            "当前安装包未绑定可用服务器，登录和专注功能无法联网。",
                            color = MaterialTheme.colorScheme.error,
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                    Text(
                        "应用禁止明文 HTTP；更换服务器需要重新构建安装包。",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
            ) {
                Column(
                    modifier = Modifier.padding(18.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text("使用说明", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text(
                        "查看开始步骤、状态含义、整屏共享与隐私说明。",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                    OutlinedButton(onClick = onOpenGuide, modifier = Modifier.fillMaxWidth()) {
                        Text("打开使用说明")
                    }
                }
            }
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
            ) {
                Row(
                    modifier = Modifier.padding(18.dp).fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text("应用版本", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text(appVersion, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            OutlinedButton(onClick = onLogout, modifier = Modifier.fillMaxWidth()) {
                Text("退出登录")
            }
            Spacer(Modifier.height(8.dp))
        }
    }
}

internal fun statusColor(status: FocusDisplayStatus): Color = when (status) {
    FocusDisplayStatus.FOCUSED -> FocusStatusColors.Focused
    FocusDisplayStatus.DISTRACTED -> FocusStatusColors.Distracted
    FocusDisplayStatus.UNCERTAIN -> FocusStatusColors.Uncertain
    FocusDisplayStatus.PENDING_REVIEW -> FocusStatusColors.PendingReview
}

private fun formatClock(seconds: Long): String {
    val safe = seconds.coerceAtLeast(0)
    return "%02d:%02d".format(safe / 60, safe % 60)
}

private fun formatReportDuration(seconds: Double?): String {
    if (seconds == null || !seconds.isFinite()) return "—"
    val safeSeconds = seconds.coerceAtLeast(0.0)
    return if (safeSeconds < 60.0) {
        String.format(Locale.getDefault(), "%.1f 秒", safeSeconds)
    } else {
        String.format(Locale.getDefault(), "%.1f 分钟", safeSeconds / 60.0)
    }
}

private fun formatPlannedMinutes(minutes: Long): String {
    val safeMinutes = minutes.coerceAtLeast(0L)
    val hours = safeMinutes / 60L
    val remainder = safeMinutes % 60L
    return when {
        hours == 0L -> "$safeMinutes 分"
        remainder == 0L -> "$hours 小时"
        else -> "${hours}时${remainder}分"
    }
}

private fun dayLabel(day: DailyCompletion): String = when (day.date.dayOfWeek.value) {
    1 -> "一"
    2 -> "二"
    3 -> "三"
    4 -> "四"
    5 -> "五"
    6 -> "六"
    else -> "日"
}

private fun formatEpochTime(epochSeconds: Double): String =
    java.time.Instant.ofEpochSecond(epochSeconds.toLong())
        .atZone(java.time.ZoneId.systemDefault())
        .format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm"))

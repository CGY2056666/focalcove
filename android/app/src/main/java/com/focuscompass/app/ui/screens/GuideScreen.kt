package com.focuscompass.app.ui.screens

import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.ExpandLess
import androidx.compose.material.icons.rounded.ExpandMore
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.focuscompass.app.ui.theme.FocusStatusColors

internal enum class GuideSectionId {
    QUICK_START,
    STATUS_AND_REPORT,
    PROJECTION_AND_PRIVACY,
    POINTS_AND_DEN,
    FAQ,
    LICENSE_AND_OPEN_SOURCE,
}

internal enum class GuideItemTone {
    DEFAULT,
    FOCUSED,
    DISTRACTED,
    UNCERTAIN,
    PENDING_REVIEW,
    NOTICE,
    QUESTION,
}

internal data class GuideItemContent(
    val title: String,
    val body: String,
    val tone: GuideItemTone = GuideItemTone.DEFAULT,
)

internal data class GuideSectionContent(
    val id: GuideSectionId,
    val number: String,
    val title: String,
    val subtitle: String,
    val intro: String,
    val items: List<GuideItemContent>,
)

internal val guideSections = listOf(
    GuideSectionContent(
        id = GuideSectionId.QUICK_START,
        number = "01",
        title = "快速开始",
        subtitle = "目标、时长、提醒与系统授权",
        intro = "一轮专注只需要四步。目标越具体，画面判断通常越容易解释。",
        items = listOf(
            GuideItemContent(
                title = "1. 写下本轮目标",
                body = "输入一轮能够完成的具体任务，例如“阅读概率论第三章并整理两道例题”。当前可选 5–120 分钟；提醒有柔和、均衡、严格三档，只改变提醒节奏，不改变模型的单帧判断。",
            ),
            GuideItemContent(
                title = "2. 确认本轮隐私说明",
                body = "开始按钮上方需要确认截图处理方式。Android 13 及以上还必须允许通知，以便整屏共享期间持续显示运行状态和提醒。",
            ),
            GuideItemContent(
                title = "3. 允许系统整屏共享",
                body = "每轮开始都会出现 Android 系统授权，应用不能静默绕过。确认后可以切换到其他应用；只要持续通知仍在，专注小窝会按采集节奏继续工作。",
            ),
            GuideItemContent(
                title = "4. 结束或放弃",
                body = "倒计时结束会自动结算，也可以提前选择“结束并生成报告”。“放弃本轮”会停止采集且不生成报告。锁屏或系统停止共享可能造成中断，中断后的时间没有画面证据。",
            ),
        ),
    ),
    GuideSectionContent(
        id = GuideSectionId.STATUS_AND_REPORT,
        number = "02",
        title = "状态与报告",
        subtitle = "四种状态、有效覆盖率与可靠性",
        intro = "首帧通常立即采集，之后约每 20 秒采集一次。网络或模型超时会跳过当次画面，不会把失败结果当作分心。",
        items = listOf(
            GuideItemContent(
                title = "专注",
                body = "当前整屏画面与文字目标有较充分的相关证据。它不代表系统能读取你的想法，也不等于心理学意义上的注意力。",
                tone = GuideItemTone.FOCUSED,
            ),
            GuideItemContent(
                title = "分心",
                body = "当前画面有较明确的偏离证据。是否发出提醒还会结合本轮提醒档位、近期结果与冷却时间。",
                tone = GuideItemTone.DISTRACTED,
            ),
            GuideItemContent(
                title = "不确定",
                body = "画面中立、正在切换、内容不足或受到安全保护时，系统无法形成明确结论；不会因为分数较低就自动算作分心。",
                tone = GuideItemTone.UNCERTAIN,
            ),
            GuideItemContent(
                title = "待复核",
                body = "当前结果尚未形成可靠结论，同样不作为明确分心处理。后续有效画面仍可继续参与本轮摘要。",
                tone = GuideItemTone.PENDING_REVIEW,
            ),
            GuideItemContent(
                title = "报告应该怎样看",
                body = "报告中的得分表示整屏画面与文字目标的相关证据，不是能力、努力程度或任务质量。优先查看实际时长、有效覆盖率、提醒次数和多轮趋势。",
                tone = GuideItemTone.NOTICE,
            ),
            GuideItemContent(
                title = "“仅供参考”是什么意思",
                body = "有效覆盖不足或没有通过可靠性检查时，报告会明确标为“仅供参考”，不会按普通成绩展示，也不会进入可靠均分。70% 是覆盖率参考线，最终以报告标记为准。",
                tone = GuideItemTone.NOTICE,
            ),
        ),
    ),
    GuideSectionContent(
        id = GuideSectionId.PROJECTION_AND_PRIVACY,
        number = "03",
        title = "投屏与隐私",
        subtitle = "截图去向、系统保护与华为近黑",
        intro = "整屏共享意味着当前屏幕可能包含敏感信息。开始前请先关闭聊天、支付、证件、密码和密钥等内容。",
        items = listOf(
            GuideItemContent(
                title = "截图怎样处理",
                body = "画面在客户端内存中缩放和压缩，通过 HTTPS 发送到专注小窝服务器，再由服务器配置的云端视觉模型分析。客户端不保存截图文件、不缓存截图，也不补传断网期间的旧画面。",
            ),
            GuideItemContent(
                title = "持续通知不能关闭",
                body = "整屏共享运行时，Android 会持续显示前台服务通知。通知消失、系统共享状态栏停止或锁屏都可能结束投屏；发生中断后，应用会停止采集并如实保留证据缺口。",
                tone = GuideItemTone.NOTICE,
            ),
            GuideItemContent(
                title = "安全页面为什么会空白",
                body = "银行、密码管理器和其他受系统保护的页面可能只返回空白或黑色区域，这是 Android 的安全机制。此类画面只会降低有效覆盖率，不会被解释为确定分心。",
                tone = GuideItemTone.UNCERTAIN,
            ),
            GuideItemContent(
                title = "华为设备出现近黑画面",
                body = "部分华为设备在投屏看似仍运行时，也可能向应用返回近乎全黑的画面。连续出现时，请先确认屏幕已解锁且持续通知仍在，再按页面提示重新授权。近黑画面按异常证据处理，不会判为确定分心。",
                tone = GuideItemTone.UNCERTAIN,
            ),
            GuideItemContent(
                title = "你始终可以停止共享",
                body = "可以从专注页结束或放弃本轮，也可以使用系统的停止共享入口。停止后，应用会释放投屏资源；重新开始下一轮时仍需再次确认系统授权。",
            ),
        ),
    ),
    GuideSectionContent(
        id = GuideSectionId.POINTS_AND_DEN,
        number = "04",
        title = "积分与小窝",
        subtitle = "可靠记录、家具兑换与房间布置",
        intro = "积分是专注小窝中的趣味反馈，不代表个人能力，也没有现金价值。",
        items = listOf(
            GuideItemContent(
                title = "积分怎样产生",
                body = "一轮记录成功保存且数据足够可靠时，服务器会结合实际记录时长、画面相关度和覆盖率计算积分。低覆盖或明确判断不足的记录可能获得 0 分。",
            ),
            GuideItemContent(
                title = "家具怎样兑换",
                body = "在“小窝”的家具商店中，可用积分兑换当前开放的虚拟家具。价格和余额由服务器校验；同一件家具只兑换一次，重复请求不会重复扣分。",
            ),
            GuideItemContent(
                title = "布置会保存到哪里",
                body = "已拥有的地板、墙面和家具可以在“布置小窝”中使用。日间或夜间氛围以及当前布置会保存到登录账号，并由服务器同步。",
            ),
            GuideItemContent(
                title = "当前奖励边界",
                body = "当前只开放虚拟小窝装扮，不对应会员、优惠券、实物、物流或退款权益。兑换前请确认物品和积分价格。",
                tone = GuideItemTone.NOTICE,
            ),
        ),
    ),
    GuideSectionContent(
        id = GuideSectionId.FAQ,
        number = "05",
        title = "常见问题",
        subtitle = "权限、采集、积分与结果解释",
        intro = "遇到异常时先看持续通知和专注页状态，不要用单次得分评价自己。",
        items = listOf(
            GuideItemContent(
                title = "为什么点开始后没有进入专注？",
                body = "请确认目标不为空、已勾选本轮隐私说明，并允许通知和系统整屏共享。拒绝通知后，需要到系统设置中重新允许；整屏共享授权每轮都要确认。",
                tone = GuideItemTone.QUESTION,
            ),
            GuideItemContent(
                title = "切到其他应用后还会采集吗？",
                body = "会。只要投屏没有被系统停止且持续通知仍在，前台服务会继续按约 20 秒的节奏采集当前整屏。锁屏、系统停止共享或进程异常可能中断。",
                tone = GuideItemTone.QUESTION,
            ),
            GuideItemContent(
                title = "为什么显示不确定或待复核？",
                body = "常见原因是画面证据不足、应用切换、安全页面、近黑画面、网络错误或模型未返回可靠结果。这两种状态都不等于分心。",
                tone = GuideItemTone.QUESTION,
            ),
            GuideItemContent(
                title = "为什么报告没有积分？",
                body = "有效覆盖率过低、有效判断画面太少、明确判断占比不足或会话中断，都可能使报告只能“仅供参考”，因此不发放积分。",
                tone = GuideItemTone.QUESTION,
            ),
            GuideItemContent(
                title = "断网后会补传截图吗？",
                body = "不会。失败采集点会被跳过，旧截图不会缓存或补传；网络恢复后只处理新的采集点。应用可能重试不包含图片的会话结算请求。",
                tone = GuideItemTone.QUESTION,
            ),
            GuideItemContent(
                title = "怎样减少误判？",
                body = "把目标写成具体动作和交付物，并查看多轮趋势。发现误判时以实际任务为准，不要为了维持分数而改变合理的学习或工作方式。",
                tone = GuideItemTone.QUESTION,
            ),
            GuideItemContent(
                title = "报告可以导出吗？",
                body = "当前 Android 版只支持在应用内查看报告和最近记录，暂未提供 PDF 或 JSON 导出。",
                tone = GuideItemTone.QUESTION,
            ),
        ),
    ),
    GuideSectionContent(
        id = GuideSectionId.LICENSE_AND_OPEN_SOURCE,
        number = "06",
        title = "开源与许可",
        subtitle = "许可证、第三方组件与品牌边界",
        intro = "本应用以 Apache License 2.0 发布，安装包内附带完整许可与第三方声明。",
        items = listOf(
            GuideItemContent(
                title = "许可证",
                body = "专注小窝的源代码与团队自有视觉资源采用 Apache License 2.0。完整文本见应用内附带的 LICENSE 与 NOTICE 文件。",
            ),
            GuideItemContent(
                title = "第三方组件",
                body = "应用使用 AndroidX、Jetpack Compose、Kotlin、Retrofit、OkHttp 等开源组件，其许可证与归属信息见 THIRD_PARTY_NOTICES.md。",
            ),
            GuideItemContent(
                title = "商标与品牌",
                body = "Apache License 2.0 不授予商标权。修改版本或二次分发不得暗示获得专注小窝团队的官方背书。",
                tone = GuideItemTone.NOTICE,
            ),
            GuideItemContent(
                title = "获取对应源码",
                body = "公开发布仓库提供对应版本的源代码与许可文件；通过安装包获取应用时，可在项目主页找到同一版本。",
            ),
        ),
    ),
)

internal fun guideContentText(): String = guideSections.joinToString(separator = "\n") { section ->
    buildString {
        append(section.title)
        append('\n')
        append(section.subtitle)
        append('\n')
        append(section.intro)
        section.items.forEach { item ->
            append('\n')
            append(item.title)
            append('\n')
            append(item.body)
        }
    }
}

@Composable
fun GuideScreen(onBack: () -> Unit) {
    WarmScreen {
        LazyColumn(
            modifier = Modifier
                .align(Alignment.TopCenter)
                .widthIn(max = 720.dp)
                .fillMaxSize(),
            contentPadding = PaddingValues(
                start = 20.dp,
                top = 10.dp,
                end = 20.dp,
                bottom = 32.dp,
            ),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            item(key = "guide-header") {
                GuideHeader(onBack = onBack)
            }
            item(key = "guide-intro") {
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.primaryContainer,
                    ),
                    shape = RoundedCornerShape(18.dp),
                ) {
                    Column(
                        modifier = Modifier.padding(18.dp),
                        verticalArrangement = Arrangement.spacedBy(7.dp),
                    ) {
                        Text(
                            "先明确目标，再把结果当作复盘线索",
                            color = MaterialTheme.colorScheme.onPrimaryContainer,
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                        )
                        Text(
                            "专注小窝判断的是整屏画面与文字目标的相关证据，不能直接判断人的注意力、情绪或任务完成质量。",
                            color = MaterialTheme.colorScheme.onPrimaryContainer,
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                }
            }
            items(
                items = guideSections,
                key = { it.id.name },
            ) { section ->
                GuideSectionCard(
                    section = section,
                    initiallyExpanded = section.id == GuideSectionId.QUICK_START,
                )
            }
            item(key = "guide-license-text") {
                GuideLicenseEntry()
            }
            item(key = "guide-footer") {
                Text(
                    "使用说明以当前 Android 版本的实际功能为准；本应用提供辅助反馈，不构成医学、心理学或教育评价。",
                    modifier = Modifier.padding(horizontal = 4.dp, vertical = 8.dp),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
    }
}

@Composable
private fun GuideLicenseEntry() {
    val context = LocalContext.current
    var showLicense by rememberSaveable { mutableStateOf(false) }
    val licenseText = remember(showLicense) {
        if (!showLicense) {
            ""
        } else {
            LICENSE_ASSETS.joinToString(separator = "\n\n") { name ->
                runCatching {
                    context.assets.open("licenses/$name").bufferedReader().use { it.readText() }
                }.getOrElse { "无法读取 $name" }
            }
        }
    }

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
        shape = RoundedCornerShape(18.dp),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                "开源许可全文",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
            )
            Text(
                "查看 Apache License 2.0、版权声明与第三方组件许可。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
            )
            TextButton(onClick = { showLicense = true }) {
                Text("查看许可文本")
            }
        }
    }

    if (showLicense) {
        AlertDialog(
            onDismissRequest = { showLicense = false },
            confirmButton = {
                TextButton(onClick = { showLicense = false }) {
                    Text("关闭")
                }
            },
            title = { Text("开源许可") },
            text = {
                Text(
                    licenseText,
                    modifier = Modifier.verticalScroll(rememberScrollState()),
                    style = MaterialTheme.typography.bodySmall,
                )
            },
        )
    }
}

private val LICENSE_ASSETS = listOf("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md")

@Composable
private fun GuideHeader(onBack: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(onClick = onBack) {
            Icon(
                imageVector = Icons.AutoMirrored.Rounded.ArrowBack,
                contentDescription = "返回",
            )
        }
        Column(
            modifier = Modifier
                .weight(1f)
                .padding(start = 4.dp, end = 8.dp, top = 8.dp, bottom = 8.dp),
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            Text(
                "使用说明",
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold,
            )
            Text(
                "从开始专注到查看报告",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun GuideSectionCard(
    section: GuideSectionContent,
    initiallyExpanded: Boolean,
) {
    var expanded by rememberSaveable(section.id.name) { mutableStateOf(initiallyExpanded) }

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(18.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .semantics {
                    stateDescription = if (expanded) "已展开" else "已收起"
                }
                .clickable(role = Role.Button) { expanded = !expanded }
                .padding(16.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Surface(
                modifier = Modifier.size(42.dp),
                color = MaterialTheme.colorScheme.primaryContainer,
                shape = CircleShape,
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Text(
                        section.number,
                        color = MaterialTheme.colorScheme.primary,
                        style = MaterialTheme.typography.labelLarge,
                        fontWeight = FontWeight.Bold,
                    )
                }
            }
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(3.dp),
            ) {
                Text(
                    section.title,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    section.subtitle,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            Icon(
                imageVector = if (expanded) Icons.Rounded.ExpandLess else Icons.Rounded.ExpandMore,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
            )
        }

        if (expanded) {
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text(
                    section.intro,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
                section.items.forEach { item ->
                    GuideItem(item)
                }
                Spacer(Modifier.height(2.dp))
            }
        }
    }
}

@Composable
private fun GuideItem(item: GuideItemContent) {
    val accent = guideToneColor(item.tone)
    val container = when (item.tone) {
        GuideItemTone.DEFAULT,
        GuideItemTone.QUESTION,
        -> MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.56f)

        GuideItemTone.NOTICE -> MaterialTheme.colorScheme.secondaryContainer.copy(alpha = 0.72f)
        else -> accent.copy(alpha = 0.10f)
    }

    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = container,
        shape = RoundedCornerShape(14.dp),
    ) {
        Row(
            modifier = Modifier.padding(14.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.Top,
        ) {
            Surface(
                modifier = Modifier
                    .padding(top = 6.dp)
                    .size(8.dp),
                color = accent,
                shape = CircleShape,
            ) {}
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(5.dp),
            ) {
                Text(
                    item.title,
                    color = if (item.tone == GuideItemTone.DEFAULT || item.tone == GuideItemTone.QUESTION) {
                        MaterialTheme.colorScheme.onSurface
                    } else {
                        accent
                    },
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    item.body,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
        }
    }
}

@Composable
private fun guideToneColor(tone: GuideItemTone): Color = when (tone) {
    GuideItemTone.FOCUSED -> FocusStatusColors.Focused
    GuideItemTone.DISTRACTED -> FocusStatusColors.Distracted
    GuideItemTone.UNCERTAIN -> FocusStatusColors.Uncertain
    GuideItemTone.PENDING_REVIEW -> FocusStatusColors.PendingReview
    GuideItemTone.NOTICE -> MaterialTheme.colorScheme.secondary
    GuideItemTone.DEFAULT,
    GuideItemTone.QUESTION,
    -> MaterialTheme.colorScheme.primary
}

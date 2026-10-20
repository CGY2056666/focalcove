package com.focuscompass.app.ui.screens

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.focuscompass.app.R
import kotlin.math.roundToInt

@Composable
fun PrivacyScreen(onAccept: () -> Unit) {
    WarmScreen(contentAlignment = Alignment.TopCenter) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .widthIn(max = 600.dp)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 24.dp, vertical = 28.dp),
            verticalArrangement = Arrangement.spacedBy(18.dp),
        ) {
            BrandLockup(subtitle = "整屏专注与云端分析")
            Spacer(Modifier.height(4.dp))
            Text(
                text = "开始前，先了解截图如何处理",
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold,
            )
            Text(
                text = "专注期间，Android 会显示系统录屏授权。授权后，应用会定时截取当前整屏，压缩后通过 HTTPS 发送到专注小窝服务器，并由服务器配置的云端视觉模型分析。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyLarge,
            )
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
            ) {
                Column(
                    modifier = Modifier.padding(20.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text("隐私边界", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    PrivacyLine("截图仅用于本轮专注判断，客户端不落盘、不缓存、不补传旧截图。")
                    PrivacyLine("银行、密码管理器等安全页面可能显示为空白，只会降低有效覆盖率。")
                    PrivacyLine("你可随时从系统通知或专注页停止整屏共享。")
                    PrivacyLine("模型密钥仅保存在服务器，不会进入 APK。")
                }
            }
            Button(onClick = onAccept, modifier = Modifier.fillMaxWidth()) {
                Text("我已理解，继续")
            }
        }
    }
}

@Composable
private fun PrivacyLine(text: String) {
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Box(
            modifier = Modifier
                .padding(top = 8.dp)
                .size(6.dp)
                .clip(CircleShape)
                .background(MaterialTheme.colorScheme.primary),
        )
        Text(text, modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable
fun AuthScreen(
    loading: Boolean,
    onSubmit: (username: String, password: String, register: Boolean) -> Unit,
) {
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var register by remember { mutableStateOf(false) }
    WarmScreen(contentAlignment = Alignment.Center) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .widthIn(max = 520.dp)
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(20.dp),
        ) {
            BrandLockup(subtitle = "把记录和专注节奏留在这里")
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
            ) {
                Column(
                    modifier = Modifier.padding(22.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    Text(
                        if (register) "创建账号" else "欢迎回来",
                        style = MaterialTheme.typography.headlineSmall,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        if (register) "创建一个账号，开始保存专注记录。" else "登录后继续你的专注计划。",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    OutlinedTextField(
                        value = username,
                        onValueChange = { username = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("用户名") },
                        singleLine = true,
                    )
                    OutlinedTextField(
                        value = password,
                        onValueChange = { password = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("密码") },
                        visualTransformation = PasswordVisualTransformation(),
                        singleLine = true,
                    )
                    Button(
                        onClick = { onSubmit(username, password, register) },
                        enabled = !loading && username.isNotBlank() && password.isNotBlank(),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        if (loading) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(20.dp),
                                color = MaterialTheme.colorScheme.onPrimary,
                                strokeWidth = 2.dp,
                            )
                        } else {
                            Text(if (register) "注册并登录" else "登录")
                        }
                    }
                    TextButton(
                        onClick = { register = !register },
                        enabled = !loading,
                        modifier = Modifier.align(Alignment.CenterHorizontally),
                    ) {
                        Text(if (register) "已有账号？返回登录" else "没有账号？创建账号")
                    }
                }
            }
        }
    }
}

@Composable
fun HomeScreen(
    username: String?,
    points: Int,
    recommendedDuration: Int?,
    serverHost: String,
    serverConfigured: Boolean,
    loading: Boolean,
    onStart: (goal: String, durationMinutes: Int, reminderMode: String) -> Unit,
) {
    var goal by remember { mutableStateOf("") }
    var duration by remember(recommendedDuration) {
        mutableFloatStateOf((recommendedDuration ?: 25).coerceIn(5, 120).toFloat())
    }
    var reminderMode by remember { mutableStateOf("medium") }
    var sessionPrivacyConfirmed by remember { mutableStateOf(false) }
    val connected = serverConfigured && username != null

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
                BrandLockup(
                    modifier = Modifier.weight(1f).padding(end = 12.dp),
                    subtitle = username?.let { "你好，$it" },
                )
                Surface(
                    color = MaterialTheme.colorScheme.primaryContainer,
                    shape = RoundedCornerShape(999.dp),
                ) {
                    Text(
                        text = "$points 积分",
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 7.dp),
                        color = MaterialTheme.colorScheme.onPrimaryContainer,
                        style = MaterialTheme.typography.labelLarge,
                        fontWeight = FontWeight.Bold,
                    )
                }
            }

            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
            ) {
                Row(
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 13.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(
                        modifier = Modifier
                            .size(9.dp)
                            .clip(CircleShape)
                            .background(if (connected) Color(0xFF2F6F5E) else MaterialTheme.colorScheme.error),
                    )
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            when {
                                !serverConfigured -> "服务器尚未配置"
                                connected -> "已安全连接"
                                else -> "正在连接服务器…"
                            },
                            style = MaterialTheme.typography.labelLarge,
                            fontWeight = FontWeight.Bold,
                        )
                        Text(
                            if (username != null) "$username · $serverHost" else serverHost,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                }
            }

            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
            ) {
                Column(
                    modifier = Modifier.padding(20.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text("开始一轮专注", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                            Text(
                                "先写下此刻唯一要完成的事。",
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                        recommendedDuration?.let {
                            Surface(
                                color = MaterialTheme.colorScheme.primaryContainer,
                                shape = RoundedCornerShape(999.dp),
                            ) {
                                Text(
                                    "建议 $it 分钟",
                                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                                    style = MaterialTheme.typography.labelMedium,
                                )
                            }
                        }
                    }
                    OutlinedTextField(
                        value = goal,
                        onValueChange = { goal = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("本轮目标") },
                        placeholder = { Text("例如：完成论文第三节") },
                        maxLines = 3,
                    )
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text("专注时长", style = MaterialTheme.typography.labelLarge)
                        Text(
                            "${duration.roundToInt()} 分钟",
                            color = MaterialTheme.colorScheme.primary,
                            style = MaterialTheme.typography.labelLarge,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                    Slider(
                        value = duration,
                        onValueChange = { duration = it },
                        valueRange = 5f..120f,
                        steps = 22,
                    )
                    Text("提醒强度", style = MaterialTheme.typography.labelLarge)
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        listOf(
                            "low" to "柔和",
                            "medium" to "均衡",
                            "high" to "严格",
                        ).forEach { (value, label) ->
                            FilterChip(
                                selected = reminderMode == value,
                                onClick = { reminderMode = value },
                                label = { Text(label) },
                                modifier = Modifier.weight(1f),
                            )
                        }
                    }
                    Text(
                        "开始前会先请求通知与系统整屏共享权限。",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.Top,
                    ) {
                        Checkbox(
                            checked = sessionPrivacyConfirmed,
                            onCheckedChange = { sessionPrivacyConfirmed = it },
                        )
                        Text(
                            "我同意本轮截图经 HTTPS 发送到服务器并由云端视觉模型处理；客户端不保存截图。",
                            modifier = Modifier.padding(top = 11.dp).weight(1f),
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                    Button(
                        onClick = { onStart(goal, duration.roundToInt(), reminderMode) },
                        enabled = !loading && goal.isNotBlank() && sessionPrivacyConfirmed,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(if (loading) "正在创建…" else "开始整屏专注")
                    }
                }
            }

            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("给今天留一小块安静的地方", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                Text(
                    "晨间计划、午后阅读或夜间冲刺，找到舒服的节奏。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            FocusSceneRow()
            Spacer(Modifier.height(8.dp))
        }
    }
}

private data class FocusScene(
    val imageRes: Int,
    val title: String,
    val subtitle: String,
)

@Composable
private fun FocusSceneRow() {
    val scenes = remember {
        listOf(
            FocusScene(R.drawable.morning_desk, "晨间计划", "从一件清楚的小事开始"),
            FocusScene(R.drawable.afternoon_reading, "午后阅读", "把注意力慢慢收回来"),
            FocusScene(R.drawable.evening_workspace, "夜间冲刺", "在安静里完成最后一段"),
        )
    }
    LazyRow(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        items(scenes) { scene ->
            Card(
                modifier = Modifier.width(248.dp),
                shape = RoundedCornerShape(18.dp),
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .aspectRatio(1.5f),
                ) {
                    Image(
                        painter = painterResource(scene.imageRes),
                        contentDescription = null,
                        modifier = Modifier.matchParentSize(),
                        contentScale = ContentScale.Crop,
                    )
                    Box(
                        modifier = Modifier
                            .matchParentSize()
                            .background(
                                Brush.verticalGradient(
                                    listOf(Color.Transparent, Color(0xCC261811)),
                                    startY = 80f,
                                ),
                            ),
                    )
                    Column(
                        modifier = Modifier
                            .align(Alignment.BottomStart)
                            .padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(2.dp),
                    ) {
                        Text(
                            scene.title,
                            color = Color.White,
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                        )
                        Text(
                            scene.subtitle,
                            color = Color.White.copy(alpha = 0.82f),
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                }
            }
        }
    }
}

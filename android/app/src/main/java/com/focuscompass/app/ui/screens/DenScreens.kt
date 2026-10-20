package com.focuscompass.app.ui.screens

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.focuscompass.app.model.DenConfig
import com.focuscompass.app.model.DenItem
import com.focuscompass.app.model.DenPayload
import com.focuscompass.app.model.isDenItemEquipped
import com.focuscompass.app.model.updateDenAmbience
import com.focuscompass.app.model.updateDenConfig
import com.focuscompass.app.ui.den.DenAssetRegistry

@Composable
fun DenScreen(
    den: DenPayload?,
    loading: Boolean,
    saving: Boolean,
    exchangingItemId: String?,
    onRefresh: () -> Unit,
    onConfigChanged: (DenConfig) -> Unit,
    onExchange: (String) -> Unit,
) {
    var shopVisible by rememberSaveable { mutableStateOf(false) }
    var pendingPurchase by remember { mutableStateOf<DenItem?>(null) }

    WarmScreen {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(
                horizontal = 20.dp,
                vertical = 22.dp,
            ),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            item {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            "我的小窝",
                            style = MaterialTheme.typography.headlineSmall,
                            fontWeight = FontWeight.Bold,
                        )
                        Text(
                            "用每一轮专注，慢慢布置自己的安静角落。",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                    Surface(
                        color = MaterialTheme.colorScheme.primaryContainer,
                        shape = RoundedCornerShape(999.dp),
                    ) {
                        Text(
                            (den?.points ?: 0).toString() + " 积分",
                            modifier = Modifier.padding(horizontal = 12.dp, vertical = 7.dp),
                            color = MaterialTheme.colorScheme.onPrimaryContainer,
                            fontWeight = FontWeight.Bold,
                            style = MaterialTheme.typography.labelLarge,
                        )
                    }
                }
            }

            item {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    FilterChip(
                        selected = !shopVisible,
                        onClick = { shopVisible = false },
                        label = { Text("布置小窝") },
                        modifier = Modifier.weight(1f),
                    )
                    FilterChip(
                        selected = shopVisible,
                        onClick = { shopVisible = true },
                        label = { Text("家具商店") },
                        modifier = Modifier.weight(1f),
                    )
                }
            }

            if (den == null) {
                item {
                    Card(
                        modifier = Modifier.fillMaxWidth(),
                        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                    ) {
                        Column(
                            modifier = Modifier.fillMaxWidth().padding(28.dp),
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.spacedBy(14.dp),
                        ) {
                            if (loading) {
                                CircularProgressIndicator()
                                Text("正在打开小窝…")
                            } else {
                                Text("暂时没有加载到小窝", fontWeight = FontWeight.Bold)
                                OutlinedButton(onClick = onRefresh) { Text("重新加载") }
                            }
                        }
                    }
                }
            } else if (!shopVisible) {
                item {
                    DenRoomPreview(den.config)
                }
                item {
                    Column(
                        modifier = Modifier.fillMaxWidth(),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        Column {
                            Text("房间氛围", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                            Text(
                                if (saving) "正在保存…" else "点击已拥有的装扮即可立即保存",
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            FilterChip(
                                selected = den.config.ambience == "day",
                                enabled = !saving,
                                onClick = {
                                    onConfigChanged(updateDenAmbience(den.config, "day"))
                                },
                                label = { Text("日间") },
                                modifier = Modifier.weight(1f),
                            )
                            FilterChip(
                                selected = den.config.ambience == "night",
                                enabled = !saving,
                                onClick = {
                                    onConfigChanged(updateDenAmbience(den.config, "night"))
                                },
                                label = { Text("夜间") },
                                modifier = Modifier.weight(1f),
                            )
                        }
                    }
                }
                item {
                    DenChoiceSection(
                        title = "地板",
                        items = den.items.filter { it.owned && it.sceneGroup == "floor" },
                        config = den.config,
                        enabled = !saving,
                        onSelect = { onConfigChanged(updateDenConfig(den.config, it)) },
                    )
                }
                item {
                    DenChoiceSection(
                        title = "墙面",
                        items = den.items.filter { it.owned && it.sceneGroup == "wall" },
                        config = den.config,
                        enabled = !saving,
                        onSelect = { onConfigChanged(updateDenConfig(den.config, it)) },
                    )
                }
                item {
                    val decorations = den.items.filter {
                        it.owned && it.sceneGroup == "decoration"
                    }
                    DenChoiceSection(
                        title = "家具",
                        items = decorations,
                        config = den.config,
                        enabled = !saving,
                        emptyMessage = "还没有家具，去商店用专注积分兑换吧。",
                        onSelect = { onConfigChanged(updateDenConfig(den.config, it)) },
                    )
                }
                item {
                    Button(
                        onClick = { shopVisible = true },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("去家具商店")
                    }
                }
            } else {
                item {
                    Card(
                        modifier = Modifier.fillMaxWidth(),
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.surfaceVariant,
                        ),
                    ) {
                        Text(
                            "这里只展示可真实兑换并摆进小窝的 10 件家具。会员和礼券仍未开放。",
                            modifier = Modifier.padding(16.dp),
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                }
                items(
                    items = den.items.filter { it.price > 0 },
                    key = { it.id },
                ) { item ->
                    ShopFurnitureCard(
                        item = item,
                        points = den.points,
                        exchanging = exchangingItemId == item.id,
                        exchangeBlocked = exchangingItemId != null,
                        onExchange = { pendingPurchase = item },
                    )
                }
                item { Spacer(Modifier.height(8.dp)) }
            }
        }
    }

    pendingPurchase?.let { item ->
        AlertDialog(
            onDismissRequest = { pendingPurchase = null },
            title = { Text("兑换" + item.name + "？") },
            text = {
                Text(
                    "将使用 " + item.price + " 积分。兑换后家具会永久加入当前 App 账号的小窝。",
                )
            },
            confirmButton = {
                Button(
                    onClick = {
                        pendingPurchase = null
                        onExchange(item.id)
                    },
                ) { Text("确认兑换") }
            },
            dismissButton = {
                TextButton(onClick = { pendingPurchase = null }) { Text("取消") }
            },
        )
    }
}

@Composable
private fun DenChoiceSection(
    title: String,
    items: List<DenItem>,
    config: DenConfig,
    enabled: Boolean,
    emptyMessage: String = "暂无可用装扮",
    onSelect: (DenItem) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        if (items.isEmpty()) {
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
            ) {
                Text(
                    emptyMessage,
                    modifier = Modifier.padding(16.dp),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        } else {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                items(items, key = { it.id }) { item ->
                    DenChoiceCard(
                        item = item,
                        selected = isDenItemEquipped(config, item),
                        enabled = enabled,
                        onClick = { onSelect(item) },
                    )
                }
            }
        }
    }
}

@Composable
private fun DenChoiceCard(
    item: DenItem,
    selected: Boolean,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    Card(
        modifier = Modifier
            .width(132.dp)
            .clickable(enabled = enabled, onClick = onClick),
        colors = CardDefaults.cardColors(
            containerColor = if (selected) {
                MaterialTheme.colorScheme.primaryContainer
            } else {
                MaterialTheme.colorScheme.surface
            },
        ),
        border = if (selected) {
            androidx.compose.foundation.BorderStroke(2.dp, MaterialTheme.colorScheme.primary)
        } else {
            null
        },
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            DenItemImage(item.id, Modifier.size(78.dp))
            Text(
                item.name,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.Bold,
            )
            Text(
                if (selected) "使用中" else "点击使用",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun ShopFurnitureCard(
    item: DenItem,
    points: Int,
    exchanging: Boolean,
    exchangeBlocked: Boolean,
    onExchange: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(
                horizontalArrangement = Arrangement.spacedBy(14.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                DenItemImage(item.id, Modifier.size(82.dp))
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(5.dp),
                ) {
                    Text(item.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text(
                        item.description,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                    Text(
                        item.price.toString() + " 积分",
                        color = MaterialTheme.colorScheme.primary,
                        style = MaterialTheme.typography.labelLarge,
                        fontWeight = FontWeight.Bold,
                    )
                }
            }
            Button(
                onClick = onExchange,
                enabled = !item.owned && points >= item.price && !exchangeBlocked,
                modifier = Modifier.fillMaxWidth(),
            ) {
                when {
                    exchanging -> CircularProgressIndicator(
                        modifier = Modifier.size(18.dp),
                        color = MaterialTheme.colorScheme.onPrimary,
                        strokeWidth = 2.dp,
                    )
                    item.owned -> Text("已拥有")
                    points < item.price -> Text("积分不足")
                    else -> Text("兑换")
                }
            }
        }
    }
}

@Composable
private fun DenRoomPreview(config: DenConfig) {
    val night = config.ambience == "night"
    val wallColor = when {
        config.wall == "star_wall" -> Color(0xFF343650)
        night -> Color(0xFF62564F)
        else -> Color(0xFFFFF9F4)
    }
    val floorColor = when (config.floor) {
        "wood_floor" -> Color(0xFFA96F4E)
        else -> if (night) Color(0xFF8D7565) else Color(0xFFDFC5B1)
    }

    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(24.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 3.dp),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .aspectRatio(1.22f)
                .background(wallColor),
        ) {
            Box(
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .fillMaxWidth()
                    .fillMaxHeight(0.32f)
                    .background(floorColor),
            )
            if (config.wall == "star_wall") {
                Text(
                    "✦   ·      ✧       ·   ✦",
                    modifier = Modifier.align(Alignment.TopCenter).padding(top = 18.dp),
                    color = Color(0xFFFFE4A3),
                    style = MaterialTheme.typography.titleLarge,
                )
            }
            Surface(
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .offset(y = (-5).dp)
                    .width(170.dp)
                    .height(42.dp),
                color = if (night) Color(0xFF8F6559) else Color(0xFFEBC5B5),
                shape = CircleShape,
            ) {}
            config.decoration.forEach { itemId ->
                DenPlacedItem(itemId)
            }
            Surface(
                modifier = Modifier.align(Alignment.TopStart).padding(12.dp),
                color = Color.Black.copy(alpha = 0.18f),
                shape = RoundedCornerShape(999.dp),
            ) {
                Text(
                    if (night) "夜间小窝" else "日间小窝",
                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                    color = Color.White,
                    style = MaterialTheme.typography.labelMedium,
                )
            }
        }
    }
}

@Composable
private fun BoxScope.DenPlacedItem(itemId: String) {
    val modifier = when (itemId) {
        "study_desk" -> Modifier.align(Alignment.BottomCenter).offset(y = (-13).dp).size(176.dp, 120.dp)
        "bookshelf" -> Modifier.align(Alignment.BottomStart).offset(x = 6.dp, y = (-22).dp).size(74.dp, 126.dp)
        "cat_nest" -> Modifier.align(Alignment.BottomEnd).offset(x = (-4).dp, y = (-2).dp).size(76.dp, 54.dp)
        "desk_lamp" -> Modifier.align(Alignment.BottomEnd).offset(x = (-62).dp, y = (-17).dp).size(52.dp, 102.dp)
        "window_curtain" -> Modifier.align(Alignment.TopEnd).offset(x = (-10).dp, y = 12.dp).size(82.dp, 94.dp)
        "plant_pot" -> Modifier.align(Alignment.BottomStart).offset(x = 74.dp, y = (-2).dp).size(48.dp, 76.dp)
        "cushion" -> Modifier.align(Alignment.BottomCenter).offset(x = (-57).dp, y = (-3).dp).size(62.dp, 42.dp)
        "wall_clock" -> Modifier.align(Alignment.TopStart).offset(x = 44.dp, y = 24.dp).size(50.dp)
        else -> Modifier.size(0.dp)
    }
    DenItemImage(itemId, modifier)
}

@Composable
private fun DenItemImage(itemId: String, modifier: Modifier = Modifier) {
    DenAssetRegistry.drawableFor(itemId)?.let { drawable ->
        Image(
            painter = painterResource(drawable),
            contentDescription = null,
            modifier = modifier,
            contentScale = ContentScale.Fit,
        )
    }
}

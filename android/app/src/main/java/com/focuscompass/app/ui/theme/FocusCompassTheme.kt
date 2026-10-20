package com.focuscompass.app.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

val BrandPrimary = Color(0xFFA84F2C)
val AccentDark = Color(0xFF873A22)
val AccentLight = Color(0xFFE7B397)
val WarmBackgroundLight = Color(0xFFFFF9F3)
val WarmBackgroundBase = Color(0xFFF8EDE3)
val WarmBackgroundDeep = Color(0xFFEFDFD1)
val WarmSurface = Color(0xFFFFFDFB)
val WarmInk = Color(0xFF33251E)
val WarmMuted = Color(0xFF6F5C50)
val WarmGold = Color(0xFFB97820)

val WarmBackgroundGradient = Brush.verticalGradient(
    colors = listOf(WarmBackgroundLight, WarmBackgroundBase, WarmBackgroundDeep),
)

object FocusStatusColors {
    val Focused = Color(0xFF2F6F5E)
    val Uncertain = Color(0xFF8A5A14)
    val Distracted = Color(0xFF9B3F30)
    val PendingReview = Color(0xFF665D57)
}

private val WarmLightColors = lightColorScheme(
    primary = BrandPrimary,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFF3E2D4),
    onPrimaryContainer = AccentDark,
    secondary = WarmGold,
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFF7E5C9),
    onSecondaryContainer = Color(0xFF5C3A0D),
    tertiary = FocusStatusColors.Focused,
    onTertiary = Color.White,
    tertiaryContainer = Color(0xFFDDECE6),
    onTertiaryContainer = Color(0xFF163C32),
    error = FocusStatusColors.Distracted,
    onError = Color.White,
    errorContainer = Color(0xFFF8DDDA),
    onErrorContainer = Color(0xFF5D211A),
    background = WarmBackgroundBase,
    onBackground = WarmInk,
    surface = WarmSurface,
    onSurface = WarmInk,
    surfaceVariant = WarmBackgroundDeep,
    onSurfaceVariant = WarmMuted,
    outline = Color(0xFF9F887A),
    outlineVariant = Color(0xFFD9CABE),
    inverseSurface = WarmInk,
    inverseOnSurface = WarmBackgroundLight,
    inversePrimary = AccentLight,
    scrim = WarmInk,
    surfaceTint = BrandPrimary,
)

private val WarmShapes = Shapes(
    extraSmall = RoundedCornerShape(10.dp),
    small = RoundedCornerShape(10.dp),
    medium = RoundedCornerShape(14.dp),
    large = RoundedCornerShape(18.dp),
    extraLarge = RoundedCornerShape(24.dp),
)

@Composable
fun FocusCompassTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = WarmLightColors,
        shapes = WarmShapes,
        content = content,
    )
}

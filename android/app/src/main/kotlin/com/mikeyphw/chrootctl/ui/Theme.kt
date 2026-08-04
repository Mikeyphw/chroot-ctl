package com.mikeyphw.chrootctl.ui

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

private val ChrootColors = darkColorScheme(
    primary = Color(0xFFB8FF69),
    onPrimary = Color(0xFF142008),
    primaryContainer = Color(0xFF31372F),
    onPrimaryContainer = Color(0xFFB8FF69),
    secondary = Color(0xFF8CC8FF),
    onSecondary = Color(0xFF06213A),
    background = Color(0xFF0F1113),
    onBackground = Color(0xFFF5F7F8),
    surface = Color(0xFF171A1D),
    onSurface = Color(0xFFF5F7F8),
    surfaceVariant = Color(0xFF202429),
    onSurfaceVariant = Color(0xFFAEB6BF),
    outline = Color(0xFF4A525C),
    outlineVariant = Color(0xFF353B42),
    error = Color(0xFFFF8D96),
    onError = Color(0xFF3B060B),
    errorContainer = Color(0xFF3A2024),
    onErrorContainer = Color(0xFFFFDADD),
)

private val ChrootShapes = Shapes(
    extraSmall = RoundedCornerShape(10.dp),
    small = RoundedCornerShape(12.dp),
    medium = RoundedCornerShape(16.dp),
    large = RoundedCornerShape(22.dp),
    extraLarge = RoundedCornerShape(28.dp),
)

private val ChrootTypography = Typography().let { base ->
    base.copy(
        displaySmall = base.displaySmall.copy(fontWeight = FontWeight.Bold),
        headlineLarge = base.headlineLarge.copy(fontWeight = FontWeight.Bold),
        headlineMedium = base.headlineMedium.copy(fontWeight = FontWeight.Bold),
        headlineSmall = base.headlineSmall.copy(fontWeight = FontWeight.SemiBold),
        titleLarge = base.titleLarge.copy(fontWeight = FontWeight.SemiBold),
        titleMedium = base.titleMedium.copy(fontWeight = FontWeight.SemiBold),
        titleSmall = base.titleSmall.copy(fontWeight = FontWeight.SemiBold),
        labelLarge = base.labelLarge.copy(fontWeight = FontWeight.SemiBold),
    )
}

val ChrootPathFont = FontFamily.Monospace

@Composable
fun ChrootCtlTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = ChrootColors,
        typography = ChrootTypography,
        shapes = ChrootShapes,
        content = content,
    )
}

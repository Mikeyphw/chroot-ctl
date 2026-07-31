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
    primary = Color(0xFFC9FF73),
    onPrimary = Color(0xFF142006),
    primaryContainer = Color(0xFF243318),
    onPrimaryContainer = Color(0xFFC9FF73),
    secondary = Color(0xFF76EADF),
    onSecondary = Color(0xFF00201D),
    background = Color(0xFF080A0C),
    onBackground = Color(0xFFF4F7F8),
    surface = Color(0xFF101417),
    onSurface = Color(0xFFF4F7F8),
    surfaceVariant = Color(0xFF171C20),
    onSurfaceVariant = Color(0xFF9AA4AD),
    outline = Color(0xFF68727C),
    error = Color(0xFFFF8E8E),
    errorContainer = Color(0xFF381F23),
)

private val ChrootShapes = Shapes(
    small = RoundedCornerShape(12.dp),
    medium = RoundedCornerShape(16.dp),
    large = RoundedCornerShape(24.dp),
)

private val ChrootTypography = Typography().let { base ->
    base.copy(
        titleLarge = base.titleLarge.copy(fontWeight = FontWeight.SemiBold),
        titleMedium = base.titleMedium.copy(fontWeight = FontWeight.SemiBold),
        headlineSmall = base.headlineSmall.copy(fontWeight = FontWeight.SemiBold),
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

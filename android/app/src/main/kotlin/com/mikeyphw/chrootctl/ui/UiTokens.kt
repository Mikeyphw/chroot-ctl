package com.mikeyphw.chrootctl.ui

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

object ChrootSpacing {
    val xxs: Dp = 4.dp
    val xs: Dp = 8.dp
    val sm: Dp = 12.dp
    val md: Dp = 16.dp
    val lg: Dp = 20.dp
    val xl: Dp = 24.dp
    val xxl: Dp = 32.dp
}

object ChrootLayout {
    val CompactNavigationBreakpoint: Dp = COMPACT_NAVIGATION_BREAKPOINT_DP.dp
    val ExpandedMetricBreakpoint: Dp = 840.dp
    val StackedHeaderBreakpoint: Dp = 560.dp
    val MaximumContentWidth: Dp = 1180.dp
    val NavigationRailWidth: Dp = 92.dp
    val MinimumTouchTarget: Dp = 48.dp
    val CompactLandscapeHeightLimit: Dp = COMPACT_LANDSCAPE_HEIGHT_LIMIT_DP.dp
}

object ChrootReleaseA11y {
    const val MinimumTouchTargetDp: Int = 48
    const val SupportedFontScalePercent: Int = 200
    const val LiveLogPollingSeconds: Int = 3
    const val SmokeProfileCount: Int = 5
    const val WorkspaceSmokeCheckCount: Int = 9
}

object ChrootStatusColors {
    val Success = Color(0xFF7EE09A)
    val Warning = Color(0xFFFFC85A)
    val Danger = Color(0xFFFF8D96)
    val Info = Color(0xFF8CC8FF)
}

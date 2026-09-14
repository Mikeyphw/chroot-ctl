package com.mikeyphw.chrootctl.ui

const val COMPACT_NAVIGATION_BREAKPOINT_DP: Float = 720f
const val TABLET_CONTENT_BREAKPOINT_DP: Float = 840f
const val DESKTOP_CONTENT_BREAKPOINT_DP: Float = 1180f
const val COMPACT_LANDSCAPE_HEIGHT_LIMIT_DP: Float = 480f
const val LARGE_TYPE_LAYOUT_THRESHOLD: Float = 1.5f
const val STACKED_HEADER_BREAKPOINT_DP: Float = 560f
const val MAX_RAIL_FONT_SCALE: Float = 2.0f

enum class PrimaryNavigationType {
    BottomBar,
    Rail,
}

enum class ReleaseWindowProfile {
    PhonePortrait,
    PhoneLandscape,
    Foldable,
    Tablet,
    DesktopWidth,
}

fun sectionHeaderStacks(availableWidthDp: Float, fontScale: Float): Boolean =
    availableWidthDp < STACKED_HEADER_BREAKPOINT_DP || fontScale >= LARGE_TYPE_LAYOUT_THRESHOLD

fun compactNavigationShowsVisualLabels(fontScale: Float): Boolean =
    fontScale <= MAX_RAIL_FONT_SCALE

fun primaryNavigationType(
    availableWidthDp: Float,
    availableHeightDp: Float = Float.MAX_VALUE,
    fontScale: Float = 1f,
): PrimaryNavigationType {
    val profile = releaseWindowProfile(availableWidthDp, availableHeightDp)
    val railAllowed = supportsNavigationRail(profile) &&
        availableHeightDp > COMPACT_LANDSCAPE_HEIGHT_LIMIT_DP &&
        fontScale < MAX_RAIL_FONT_SCALE
    return if (railAllowed) PrimaryNavigationType.Rail else PrimaryNavigationType.BottomBar
}

fun releaseWindowProfile(availableWidthDp: Float, availableHeightDp: Float): ReleaseWindowProfile {
    return when {
        availableWidthDp >= DESKTOP_CONTENT_BREAKPOINT_DP -> ReleaseWindowProfile.DesktopWidth
        availableWidthDp >= TABLET_CONTENT_BREAKPOINT_DP -> ReleaseWindowProfile.Tablet
        availableWidthDp >= COMPACT_NAVIGATION_BREAKPOINT_DP -> ReleaseWindowProfile.Foldable
        availableHeightDp <= COMPACT_LANDSCAPE_HEIGHT_LIMIT_DP -> ReleaseWindowProfile.PhoneLandscape
        else -> ReleaseWindowProfile.PhonePortrait
    }
}

fun supportsNavigationRail(profile: ReleaseWindowProfile): Boolean = when (profile) {
    ReleaseWindowProfile.PhonePortrait,
    ReleaseWindowProfile.PhoneLandscape -> false
    ReleaseWindowProfile.Foldable,
    ReleaseWindowProfile.Tablet,
    ReleaseWindowProfile.DesktopWidth -> true
}

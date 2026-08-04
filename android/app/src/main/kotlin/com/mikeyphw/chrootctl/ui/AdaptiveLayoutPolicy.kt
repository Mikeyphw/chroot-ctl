package com.mikeyphw.chrootctl.ui

const val COMPACT_NAVIGATION_BREAKPOINT_DP: Float = 720f
const val TABLET_CONTENT_BREAKPOINT_DP: Float = 840f
const val DESKTOP_CONTENT_BREAKPOINT_DP: Float = 1180f
const val COMPACT_LANDSCAPE_HEIGHT_LIMIT_DP: Float = 480f

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

fun primaryNavigationType(availableWidthDp: Float): PrimaryNavigationType {
    return if (availableWidthDp >= COMPACT_NAVIGATION_BREAKPOINT_DP) {
        PrimaryNavigationType.Rail
    } else {
        PrimaryNavigationType.BottomBar
    }
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

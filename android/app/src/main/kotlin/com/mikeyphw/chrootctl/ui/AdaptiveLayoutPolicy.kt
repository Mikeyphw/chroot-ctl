package com.mikeyphw.chrootctl.ui

const val COMPACT_NAVIGATION_BREAKPOINT_DP: Float = 720f

enum class PrimaryNavigationType {
    BottomBar,
    Rail,
}

fun primaryNavigationType(availableWidthDp: Float): PrimaryNavigationType {
    return if (availableWidthDp >= COMPACT_NAVIGATION_BREAKPOINT_DP) {
        PrimaryNavigationType.Rail
    } else {
        PrimaryNavigationType.BottomBar
    }
}

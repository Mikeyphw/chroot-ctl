package com.mikeyphw.chrootctl.ui

data class ReleaseSmokeProfile(
    val id: String,
    val minWidthDp: Int,
    val maxWidthDp: Int?,
    val minHeightDp: Int,
    val navigationType: PrimaryNavigationType,
)

object ReleaseUxPolicy {
    const val minimumTouchTargetDp: Int = 48
    const val supportedFontScalePercent: Int = 200
    const val maximumContentWidthDp: Int = 1180
    const val liveLogPollingSeconds: Int = 3

    val smokeProfiles: List<ReleaseSmokeProfile> = listOf(
        ReleaseSmokeProfile("phone-portrait", minWidthDp = 360, maxWidthDp = 479, minHeightDp = 720, navigationType = PrimaryNavigationType.BottomBar),
        ReleaseSmokeProfile("phone-landscape", minWidthDp = 640, maxWidthDp = 719, minHeightDp = 360, navigationType = PrimaryNavigationType.BottomBar),
        ReleaseSmokeProfile("foldable", minWidthDp = 720, maxWidthDp = 839, minHeightDp = 600, navigationType = PrimaryNavigationType.Rail),
        ReleaseSmokeProfile("tablet", minWidthDp = 840, maxWidthDp = 1179, minHeightDp = 720, navigationType = PrimaryNavigationType.Rail),
        ReleaseSmokeProfile("desktop-width", minWidthDp = 1180, maxWidthDp = null, minHeightDp = 720, navigationType = PrimaryNavigationType.Rail),
    )

    val releaseRoutes: List<AppDestination> = listOf(
        AppDestination.Home,
        AppDestination.Chroots,
        AppDestination.Install,
        AppDestination.Activity,
        AppDestination.Tools,
    )

    val accessibilitySealChecks: List<String> = listOf(
        "minimum-48dp-touch-targets",
        "pane-title-per-destination",
        "pane-title-per-workspace-room",
        "heading-per-screen",
        "font-scale-200-percent",
        "talkback-labels-for-navigation",
        "keyboard-traversal-groups",
        "bounded-live-log-polling",
        "no-automatic-mutating-replay",
        "mutation-review-state-not-saveable",
    )

    val workspaceStateSealChecks: Set<WorkspacePaneState> = WorkspacePaneState.entries.toSet()

    val realDeviceWorkspaceSmokeChecks: List<String> = listOf(
        "root-module-discovery",
        "root-service-reconnect",
        "services-workspace",
        "users-workspace",
        "snapshots-workspace",
        "storage-workspace",
        "logs-workspace",
        "advanced-workspace",
        "degraded-protocol-fallback",
    )

    fun smokeProfileIds(): Set<String> = smokeProfiles.mapTo(linkedSetOf()) { it.id }

    fun supportsFontScale(percent: Int): Boolean = percent in 100..supportedFontScalePercent

    fun validatesReleaseContract(): Boolean {
        return minimumTouchTargetDp == ChrootReleaseA11y.MinimumTouchTargetDp &&
            supportedFontScalePercent == ChrootReleaseA11y.SupportedFontScalePercent &&
            maximumContentWidthDp == ChrootLayout.MaximumContentWidth.value.toInt() &&
            liveLogPollingSeconds == ChrootReleaseA11y.LiveLogPollingSeconds &&
            smokeProfiles.size == ChrootReleaseA11y.SmokeProfileCount &&
            releaseRoutes == AppDestination.entries &&
            workspaceStateSealChecks == WorkspacePaneState.entries.toSet() &&
            realDeviceWorkspaceSmokeChecks.size == ChrootReleaseA11y.WorkspaceSmokeCheckCount
    }
}

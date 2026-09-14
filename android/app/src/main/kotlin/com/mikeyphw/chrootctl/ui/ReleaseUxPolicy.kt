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
    const val maxNavigationBackStackDepth: Int = 32
    const val maximumNavigationRailFontScale: Float = MAX_RAIL_FONT_SCALE

    val smokeProfiles: List<ReleaseSmokeProfile> = listOf(
        ReleaseSmokeProfile("phone-portrait", minWidthDp = 360, maxWidthDp = 479, minHeightDp = 720, navigationType = PrimaryNavigationType.BottomBar),
        ReleaseSmokeProfile("phone-landscape", minWidthDp = 640, maxWidthDp = 719, minHeightDp = 360, navigationType = PrimaryNavigationType.BottomBar),
        ReleaseSmokeProfile("foldable", minWidthDp = 720, maxWidthDp = 839, minHeightDp = 600, navigationType = PrimaryNavigationType.Rail),
        ReleaseSmokeProfile("tablet", minWidthDp = 840, maxWidthDp = 1179, minHeightDp = 720, navigationType = PrimaryNavigationType.Rail),
        ReleaseSmokeProfile("desktop-width", minWidthDp = 1180, maxWidthDp = null, minHeightDp = 720, navigationType = PrimaryNavigationType.Rail),
    )

    val releaseRoutes: List<AppDestination> = AppDestination.entries.toList()

    val accessibilitySealChecks: List<String> = listOf(
        "minimum-48dp-touch-targets",
        "system-predictive-back-stack",
        "notification-deeplink-proved-before-navigation",
        "runtime-window-policy-executable",
        "pane-title-per-destination",
        "pane-title-per-workspace-room",
        "heading-per-screen",
        "font-scale-200-percent",
        "talkback-labels-for-navigation",
        "selected-semantics-for-custom-controls",
        "live-region-status-announcements",
        "lazy-collection-semantics",
        "keyboard-traversal-groups",
        "bounded-live-log-polling",
        "no-automatic-mutating-replay",
        "mutation-review-state-not-saveable",
        "binder-lifecycle-instrumentation-plan",
        "final-gate-validates-all-overlays",
    )

    val workspaceStateSealChecks: Set<WorkspacePaneState> = WorkspacePaneState.entries.toSet()

    val finalGateCommands: List<String> = listOf(
        "go run ./cmd/cli-contract-gen --check",
        "go run ./cmd/repoctl validate",
        "android:chrootctlDebugValidation",
    )

    val androidInstrumentationSealChecks: List<String> = listOf(
        "binder-death-read-only-replay-once",
        "binder-death-mutation-not-replayed",
        "operation-notification-deeplink-proven",
        "predictive-back-stack-pop",
    )

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
            realDeviceWorkspaceSmokeChecks.size == ChrootReleaseA11y.WorkspaceSmokeCheckCount &&
            maxNavigationBackStackDepth == NavigationReleasePolicy.maxBackStackDepth &&
            finalGateCommands.contains("go run ./cmd/repoctl validate") &&
            androidInstrumentationSealChecks.contains("binder-death-read-only-replay-once")
    }
}

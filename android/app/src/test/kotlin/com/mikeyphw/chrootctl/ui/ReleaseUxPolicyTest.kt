package com.mikeyphw.chrootctl.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ReleaseUxPolicyTest {
    @Test
    fun `release profiles cover phone landscape foldable tablet and desktop`() {
        assertEquals(
            setOf("phone-portrait", "phone-landscape", "foldable", "tablet", "desktop-width"),
            ReleaseUxPolicy.smokeProfileIds(),
        )
        assertEquals(ReleaseWindowProfile.PhonePortrait, releaseWindowProfile(390f, 844f))
        assertEquals(ReleaseWindowProfile.PhoneLandscape, releaseWindowProfile(640f, 360f))
        assertEquals(ReleaseWindowProfile.Foldable, releaseWindowProfile(720f, 720f))
        assertEquals(ReleaseWindowProfile.Tablet, releaseWindowProfile(900f, 900f))
        assertEquals(ReleaseWindowProfile.DesktopWidth, releaseWindowProfile(1180f, 900f))
    }

    @Test
    fun `release accessibility contract remains explicit`() {
        assertTrue(ReleaseUxPolicy.validatesReleaseContract())
        assertTrue(ReleaseUxPolicy.supportsFontScale(200))
        assertFalse(ReleaseUxPolicy.supportsFontScale(201))
        assertTrue(ReleaseUxPolicy.accessibilitySealChecks.contains("minimum-48dp-touch-targets"))
        assertTrue(ReleaseUxPolicy.accessibilitySealChecks.contains("system-predictive-back-stack"))
        assertTrue(ReleaseUxPolicy.accessibilitySealChecks.contains("notification-deeplink-proved-before-navigation"))
        assertTrue(ReleaseUxPolicy.accessibilitySealChecks.contains("no-automatic-mutating-replay"))
        assertTrue(ReleaseUxPolicy.finalGateCommands.contains("go run ./cmd/repoctl validate"))
        assertTrue(ReleaseUxPolicy.androidInstrumentationSealChecks.contains("binder-death-read-only-replay-once"))
        assertTrue(ReleaseUxPolicy.androidInstrumentationSealChecks.contains("predictive-back-stack-pop"))
    }
    @Test
    fun `phase 41 accessibility seal covers pane state restoration and traversal`() {
        assertEquals(4, ReleaseUxPolicy.workspaceStateSealChecks.size)
        assertTrue(ReleaseUxPolicy.accessibilitySealChecks.contains("pane-title-per-workspace-room"))
        assertTrue(ReleaseUxPolicy.accessibilitySealChecks.contains("keyboard-traversal-groups"))
        assertTrue(ReleaseUxPolicy.accessibilitySealChecks.contains("mutation-review-state-not-saveable"))
        assertTrue(WorkspaceRestorationPolicy.maySave("workspace-tab"))
        assertTrue(WorkspaceRestorationPolicy.maySave("logs-live-tail"))
        assertFalse(WorkspaceRestorationPolicy.maySave("snapshot-review"))
        assertFalse(WorkspaceRestorationPolicy.maySave("service-review"))
    }

    @Test
    fun `phase 41 adaptive header and compact nav remain usable at large font scale`() {
        assertTrue(sectionHeaderStacks(390f, 1f))
        assertFalse(sectionHeaderStacks(640f, 1f))
        assertFalse(sectionHeaderStacks(900f, 1f))
        assertTrue(sectionHeaderStacks(900f, 2f))
        assertTrue(compactNavigationShowsVisualLabels(1.49f))
        assertTrue(compactNavigationShowsVisualLabels(1.5f))
        assertTrue(compactNavigationShowsVisualLabels(2f))
        assertEquals(PrimaryNavigationType.BottomBar, primaryNavigationType(720f, 360f, 1f))
    }

    @Test
    fun `phase 42 real device smoke seal covers every selected chroot room`() {
        assertEquals(
            listOf(
                "root-module-discovery",
                "root-service-reconnect",
                "services-workspace",
                "users-workspace",
                "snapshots-workspace",
                "storage-workspace",
                "logs-workspace",
                "advanced-workspace",
                "degraded-protocol-fallback",
            ),
            ReleaseUxPolicy.realDeviceWorkspaceSmokeChecks,
        )
    }

}

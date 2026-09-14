package com.mikeyphw.chrootctl.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class NavigationReleasePolicyChr20Test {
    @Test
    fun `CHR20 destination stack sanitizes restores pushes and pops predictably`() {
        val restored = NavigationReleasePolicy.sanitizeDestinationStack(
            listOf("Missing", AppDestination.Home.name, AppDestination.Home.name, AppDestination.Tools.name),
        )
        assertEquals(listOf(AppDestination.Home.name, AppDestination.Tools.name), restored)

        val pushed = NavigationReleasePolicy.pushDestinationStack(restored, AppDestination.Activity)
        assertEquals(AppDestination.Activity.name, pushed.last())
        assertEquals(restored, NavigationReleasePolicy.popDestinationStack(pushed))
        assertEquals(listOf(AppDestination.Home.name), NavigationReleasePolicy.popDestinationStack(listOf(AppDestination.Home.name)))
    }

    @Test
    fun `CHR20 notification deep links must be proven before navigation`() {
        assertEquals(DeepLinkDecision.Ignore, NavigationReleasePolicy.deepLinkDecision("", setOf("op-1")))
        assertEquals(DeepLinkDecision.WaitForSnapshot, NavigationReleasePolicy.deepLinkDecision("op-2", setOf("op-1")))
        assertEquals(DeepLinkDecision.Open, NavigationReleasePolicy.deepLinkDecision("op-1", setOf("op-1")))
    }

    @Test
    fun `CHR20 adaptive policy uses height and font scale not width alone`() {
        assertEquals(PrimaryNavigationType.Rail, primaryNavigationType(720f, 720f, 1f))
        assertEquals(PrimaryNavigationType.BottomBar, primaryNavigationType(720f, 360f, 1f))
        assertEquals(PrimaryNavigationType.BottomBar, primaryNavigationType(900f, 900f, 2f))
        assertTrue(compactNavigationShowsVisualLabels(2f))
    }

    @Test
    fun `CHR20 restored removed workspace names are discarded`() {
        assertEquals("debian", restoreWorkspaceNameOrNull("debian", setOf("debian", "arch")))
        assertNull(restoreWorkspaceNameOrNull("missing", setOf("debian", "arch")))
        assertFalse(restoredWorkspaceUnavailable("debian", setOf("debian")))
        assertTrue(restoredWorkspaceUnavailable("missing", setOf("debian")))
    }
}

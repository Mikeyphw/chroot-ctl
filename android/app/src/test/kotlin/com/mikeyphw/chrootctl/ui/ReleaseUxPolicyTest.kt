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
        assertTrue(ReleaseUxPolicy.accessibilitySealChecks.contains("no-automatic-mutating-replay"))
    }
}

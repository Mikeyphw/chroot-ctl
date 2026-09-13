package com.mikeyphw.chrootctl.root

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RootTrustBoundaryTest {
    @Test
    fun `root bridge environment excludes Termux and caller paths`() {
        val env = rootBridgeEnvironment()
        assertEquals("/data/adb/chrootctl", env["HOME"])
        val path = requireNotNull(env["PATH"])
        assertTrue(path.startsWith("/data/adb/chrootctl/bin:"))
        assertFalse(path.contains("com.termux"))
        assertFalse(path.contains(".local/bin"))
    }

    @Test
    fun `trusted runtime metadata requires root ownership and immutable mode`() {
        assertTrue(trustedRootExecutableMetadata(uid = 0, mode = 0x81ED))
        assertFalse(trustedRootExecutableMetadata(uid = 2000, mode = 0x81ED))
        assertFalse(trustedRootExecutableMetadata(uid = 0, mode = 0x81FD))
        assertFalse(trustedRootExecutableMetadata(uid = 0, mode = 0x81EF))
    }
}

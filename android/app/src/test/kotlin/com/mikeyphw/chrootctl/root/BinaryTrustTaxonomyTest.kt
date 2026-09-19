package com.mikeyphw.chrootctl.root

import org.junit.Assert.assertTrue
import org.junit.Test

class BinaryTrustTaxonomyTest {
    @Test fun `technical report carries trust metadata`() {
        val probe = BinaryCandidateProbe("/data/adb/modules/chrootctl-magisk/system/bin/chrootctl", "module-launcher", true, true, false, false, null, "owner uid 2000 is not root (expected 0)", 2000, 2000, 0x1ed, "/data/adb/modules/chrootctl-magisk/system/bin/chrootctl")
        val report = BinaryResolutionReport("BINARY_OWNER_INVALID", null, null, true, false, true, false, "/system/bin", "KernelSU", "arm64-v8a", listOf(probe)).toJson().toString()
        assertTrue(report.contains("BINARY_OWNER_INVALID"))
        assertTrue(report.contains("uid"))
        assertTrue(report.contains("canonicalPath"))
    }
}


class BinaryTrustMetadataTest {
    @Test fun `root owned 0755 launcher metadata is trusted`() {
        assertTrue(trustedRootExecutableMetadata(0, 0x1ed))
    }

    @Test fun `group or other writable launcher metadata is rejected`() {
        assertTrue(!trustedRootExecutableMetadata(0, 0x1fd))
        assertTrue(!trustedRootExecutableMetadata(0, 0x1ef))
    }

    @Test fun `non root launcher metadata is rejected`() {
        assertTrue(!trustedRootExecutableMetadata(2000, 0x1ed))
    }
}

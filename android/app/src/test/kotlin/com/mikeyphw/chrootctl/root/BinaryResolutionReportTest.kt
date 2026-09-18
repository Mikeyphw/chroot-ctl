package com.mikeyphw.chrootctl.root

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class BinaryResolutionReportTest {
    @Test
    fun `failure report is actionable and preserves every checked candidate`() {
        val report = BinaryResolutionReport(
            code = "PUBLIC_LAUNCHER_MISSING",
            selectedPath = null,
            selectedSource = null,
            moduleInstalled = true,
            moduleDisabled = false,
            moduleSealReady = true,
            pendingUpdate = false,
            path = "/data/adb/chrootctl/bin:/system/bin:/system/xbin",
            rootProvider = "KernelSU",
            abi = "arm64-v8a",
            candidates = listOf(
                BinaryCandidateProbe("/data/adb/chrootctl/bin/chrootctl", "public-launcher", false, false, false, false, null, "not found"),
                BinaryCandidateProbe("/system/bin/chrootctl", "public-launcher", false, false, false, false, null, "not found"),
            ),
        )
        val json = report.toJson()
        assertEquals("PUBLIC_LAUNCHER_MISSING", json.getString("code"))
        assertEquals(2, json.getJSONArray("candidates").length())
        assertTrue(report.summary().contains("Reinstall/update"))
        assertTrue(report.summary().contains("/system/bin/chrootctl"))
    }

    @Test
    fun `successful report names absolute selected launcher`() {
        val report = BinaryResolutionReport(
            code = "OK",
            selectedPath = "/data/adb/chrootctl/bin/chrootctl",
            selectedSource = "public-launcher",
            moduleInstalled = true,
            moduleDisabled = false,
            moduleSealReady = true,
            pendingUpdate = false,
            path = "/data/adb/chrootctl/bin:/system/bin",
            rootProvider = "Magisk",
            abi = "arm64-v8a",
            candidates = emptyList(),
        )
        assertTrue(report.summary().contains("/data/adb/chrootctl/bin/chrootctl"))
    }
}

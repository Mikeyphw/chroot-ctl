package com.mikeyphw.chrootctl.ui

import com.mikeyphw.chrootctl.model.TransferPane
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RcloneRemoteTransferUxTest {
    private fun repoRoot(): File {
        var current = File(System.getProperty("user.dir") ?: ".").canonicalFile
        repeat(8) {
            if (File(current, ".devtool.toml").isFile && File(current, "android/build.gradle.kts").isFile) return current
            current = current.parentFile ?: error("Unable to locate repository root")
        }
        error("Unable to locate repository root")
    }

    @Test
    fun `remote transfer defaults are explicit and fail closed`() {
        val pane = TransferPane()
        assertEquals("auto", pane.importStrategy)
        assertFalse(pane.rcloneAvailable)
        assertFalse(pane.rcloneConfigured)
        assertTrue(pane.rcloneRemotes.isEmpty())
        assertTrue(pane.rcloneEntries.isEmpty())
    }

    @Test
    fun `Android bridge and UI expose credential free rclone transport`() {
        val root = repoRoot()
        val repository = File(root, "android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt").readText()
        val viewModel = File(root, "android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt").readText()
        val tools = File(root, "android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/tools/ToolsScreen.kt").readText()
        val activity = File(root, "android/app/src/main/kotlin/com/mikeyphw/chrootctl/MainActivity.kt").readText()

        listOf("remote.rclone.status", "remote.rclone.list").forEach { token ->
            assertTrue("Repository missing $token", token in repository)
        }
        assertTrue("Import strategy must cross the Android bridge", ".put(\"importStrategy\", importStrategy)" in repository)
        assertTrue("Execution payload must preserve import strategy", ".put(\"importStrategy\", current.importStrategy)" in viewModel)
        val app = root.resolve("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootCtlApp.kt").readText()
        assertTrue("Rclone config import must use the dedicated backend operation", "remote.rclone.config_import" in app)
        assertTrue("Successful config import must clear the staged credential path", "clearRcloneStagedConfig()" in app)
        assertTrue("Remote browser must use credential-free rclone URIs", "rclone://\$remoteName/" in tools)
        assertTrue("Remote folder selection must synthesize an archive filename for export", "\$current/\$baseName.tar.zst" in tools)
        assertTrue("Android must provide a document picker for rclone.conf", "pickRcloneConfig" in activity && "stageRcloneConfig" in activity)
        assertTrue("Rclone progress must preserve transfer rate", "rate_bytes_per_second" in repository)
        assertTrue("Rclone progress must preserve ETA", "eta_seconds" in repository)
        assertTrue("Rclone progress must preserve the active remote object", "current_object" in repository)
    }
}

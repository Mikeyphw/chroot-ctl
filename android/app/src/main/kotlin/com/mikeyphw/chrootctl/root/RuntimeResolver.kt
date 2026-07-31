package com.mikeyphw.chrootctl.root

import java.io.File

internal data class BridgeRuntime(
    val argv: List<String>,
    val backend: String,
    val executable: String,
)

internal object RuntimeResolver {
    private val executableCandidates = listOf(
        "/data/adb/chrootctl/bin/chrootctl",
        "/data/data/com.termux/files/usr/bin/chrootctl",
        "/system/bin/chrootctl",
    )
    private val pythonCandidates = listOf(
        "/data/adb/chrootctl/python/bin/python3",
        "/data/data/com.termux/files/usr/bin/python3",
        "/data/data/com.termux/files/usr/bin/python",
    )

    fun resolve(): BridgeRuntime? {
        val override = System.getenv("CHROOTCTL_EXECUTABLE")?.takeIf(String::isNotBlank)
        if (override != null && isExecutable(override)) {
            return BridgeRuntime(listOf(override, "app"), "override", override)
        }
        executableCandidates.firstOrNull(::isExecutable)?.let { executable ->
            return BridgeRuntime(listOf(executable, "app"), "chrootctl", executable)
        }
        pythonCandidates.firstOrNull(::isExecutable)?.let { python ->
            return BridgeRuntime(listOf(python, "-m", "chrootctl.bridge.cli"), "python-module", python)
        }
        return null
    }

    private fun isExecutable(path: String): Boolean = File(path).let { it.isFile && it.canExecute() }
}

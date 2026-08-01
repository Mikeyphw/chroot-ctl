package com.mikeyphw.chrootctl.root

import java.io.File

internal data class BridgeRuntime(
    val argv: List<String>,
    val backend: String,
    val executable: String,
)

internal object RuntimeResolver {
    private val dataRoot = File(File.separator, "data")
    private val adbRoot = File(dataRoot, "adb")
    private val termuxRoot = File(File(dataRoot, "data"), "com.termux")
    private val termuxUsr = File(termuxRoot, "files/usr")

    private val executableCandidates = listOf(
        File(adbRoot, "chrootctl/bin/chrootctl"),
        File(termuxUsr, "bin/chrootctl"),
        File(File.separator, "system/bin/chrootctl"),
    )
    private val pythonCandidates = listOf(
        File(adbRoot, "chrootctl/python/bin/python3"),
        File(termuxUsr, "bin/python3"),
        File(termuxUsr, "bin/python"),
    )

    fun resolve(): BridgeRuntime? {
        val override = System.getenv("CHROOTCTL_EXECUTABLE")?.takeIf(String::isNotBlank)
        if (override != null && isExecutable(File(override))) {
            return BridgeRuntime(listOf(override, "app"), "override", override)
        }
        executableCandidates.firstOrNull(::isExecutable)?.let { executable ->
            val path = executable.path
            return BridgeRuntime(listOf(path, "app"), "chrootctl", path)
        }
        pythonCandidates.firstOrNull(::isExecutable)?.let { python ->
            val path = python.path
            return BridgeRuntime(listOf(path, "-m", "chrootctl.bridge.cli"), "python-module", path)
        }
        return null
    }

    private fun isExecutable(path: File): Boolean = path.isFile && path.canExecute()
}

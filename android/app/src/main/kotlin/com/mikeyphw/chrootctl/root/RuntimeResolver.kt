package com.mikeyphw.chrootctl.root

import java.io.File
import org.json.JSONObject

internal data class BridgeRuntime(
    val argv: List<String>,
    val backend: String,
    val executable: String,
)

internal object RuntimeResolver {
    private val dataRoot = File(File.separator, "data")
    private val adbRoot = File(dataRoot, "adb")
    private val termuxRoot = File(File(dataRoot, "data"), "com.termux")
    private val termuxFiles = File(termuxRoot, "files")
    private val termuxUsr = File(termuxFiles, "usr")
    private val termuxHome = File(termuxFiles, "home")

    private val ksuRoot = File(adbRoot, "ksu")
    private val rootModuleExecutableCandidates = listOf(
        File(adbRoot, "modules/chrootctl-magisk/system/bin/chrootctl"),
        File(adbRoot, "modules_update/chrootctl-magisk/system/bin/chrootctl"),
        File(ksuRoot, "modules/chrootctl-magisk/system/bin/chrootctl"),
        File(ksuRoot, "modules_update/chrootctl-magisk/system/bin/chrootctl"),
    )
    private val executableCandidates = rootModuleExecutableCandidates + listOf(
        File(File.separator, "system/bin/chrootctl"),
        File(adbRoot, "chrootctl/bin/chrootctl"),
        File(termuxHome, ".local/bin/chrootctl"),
        File(termuxUsr, "bin/chrootctl"),
    )
    private val pythonCandidates = listOf(
        File(adbRoot, "chrootctl/python/bin/python3"),
        File(termuxUsr, "bin/python3"),
        File(termuxUsr, "bin/python"),
    )

    @Volatile private var cachedRuntime: BridgeRuntime? = null
    @Volatile private var lastDiagnostic: String = "No compatible chrootctl Android bridge runtime has been resolved"

    fun resolve(): BridgeRuntime? {
        cachedRuntime?.let { cached ->
            if (isExecutable(File(cached.executable))) return cached
            cachedRuntime = null
        }
        return synchronized(this) {
            cachedRuntime?.let { return@synchronized it }
            val override = System.getenv("CHROOTCTL_EXECUTABLE")?.takeIf(String::isNotBlank)
            if (override != null) {
                val candidate = File(override)
                val runtime = BridgeRuntime(listOf(override, "app"), "override", override)
                if (isExecutable(candidate) && isCompatible(runtime)) {
                    lastDiagnostic = "Using compatible bridge runtime at $override"
                    cachedRuntime = runtime
                    return@synchronized runtime
                }
                lastDiagnostic = "CHROOTCTL_EXECUTABLE does not point to a compatible protocol-1 Android bridge"
                return@synchronized null
            }

            val candidates = buildList {
                executableCandidates.filter(::isExecutable).forEach { executable ->
                    add(BridgeRuntime(listOf(executable.path, "app"), "chrootctl", executable.path))
                }
                pythonCandidates.filter(::isExecutable).forEach { python ->
                    add(BridgeRuntime(listOf(python.path, "-m", "chrootctl.bridge.cli"), "python-module", python.path))
                }
            }
            val selected = selectCompatibleRuntime(candidates, ::isCompatible)
            if (selected == null) {
                lastDiagnostic = if (candidates.isEmpty()) {
                    "No chrootctl executable or Python runtime was found in the Magisk/KSU module, system, legacy adb-root, or Termux locations"
                } else {
                    "Found chrootctl runtime candidates, but none exposed the protocol-1 Android bridge"
                }
            } else {
                lastDiagnostic = "Using compatible bridge runtime at ${selected.executable}"
            }
            cachedRuntime = selected
            selected
        }
    }

    fun diagnostic(): String = lastDiagnostic

    fun invalidate(runtime: BridgeRuntime) {
        synchronized(this) {
            if (cachedRuntime == runtime) cachedRuntime = null
        }
    }

    private fun isCompatible(runtime: BridgeRuntime): Boolean {
        val result = runCatching {
            BridgeProcess(runtime).invoke(listOf("capabilities"), timeoutSeconds = PROBE_TIMEOUT_SECONDS)
        }.getOrNull() ?: return false
        val accepted = validateBridgeProcessResult(runtime, result) as? BridgeOutputValidation.Accepted ?: return false
        val envelope = runCatching { JSONObject(accepted.json) }.getOrNull() ?: return false
        val data = envelope.optJSONObject("data") ?: return false
        return result.exitCode == 0 &&
            envelope.optBoolean("ok") &&
            data.optInt("protocolVersion", -1) == BRIDGE_PROTOCOL_VERSION
    }

    private fun isExecutable(path: File): Boolean = path.isFile && path.canExecute()

    private const val PROBE_TIMEOUT_SECONDS = 2L
    private const val BRIDGE_PROTOCOL_VERSION = 1
}

internal fun selectCompatibleRuntime(
    candidates: List<BridgeRuntime>,
    probe: (BridgeRuntime) -> Boolean,
): BridgeRuntime? = candidates.firstOrNull(probe)
